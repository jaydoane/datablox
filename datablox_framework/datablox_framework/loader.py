import os
import sys
import zmq
import json
import time
from element import *
from shard import *

class Master(object):
  def __init__(self, config_file):
    self.master_port = 6500
    self.blox_run_dir = "/Users/saideep/Downloads/blox"
    self.element_classes = []
    self.elements = {}
    self.loads = {}
    self.shard_nodes = {}
    self.num_parallel = 0
    self.ip_pick = 0
    self.ipaddress_hash = self.get_ipaddress_hash()
    self.context = zmq.Context()
    self.port_num_gen = PortNumberGenerator()
    # os.system("cd " + self.blox_run_dir + " && rm *")
    # self.load_elements(os.environ["BLOXPATH"])
    self.setup_connections(config_file)
    self.start_elements()
    self.run()

  #TODO: Fix this
  def get_ipaddress_hash(self):
    ipaddresses = ["139.19.157.13", "139.19.192.14", "139.19.193.85", "139.19.157.14"]
    #ipaddresses = ["139.19.192.14"]
    d = {}
    for ip in ipaddresses:
      d[ip] = 0
    return d
  
  def select_ipaddress(self):
    #select the node which has the least number of running elements
    min_ip = (None, 100000)
    for k, v in self.ipaddress_hash.items():
      if min_ip[1] > v:
        min_ip = (k, v)
    #increment the elements on this one
    self.ipaddress_hash[min_ip[0]] = min_ip[1] + 1
    return min_ip[0]
    
  def element_path(self, element_name):
    file_name = 'e_' + element_name.lower().replace('-', '_') + '.py'
    return os.path.join(os.environ["BLOXPATH"], file_name)
  
  def element_class_name(self, element_name):
    return element_name.lower().replace('-', '_')
    
  def create_element(self, name, config, pin_ipaddress=None):
    path = self.element_path(name)
    if not os.path.isfile(path):
      print "Could not find the element " + path
      raise NameError
    
    if pin_ipaddress == None:
      ipaddress = self.select_ipaddress()
    else:
      print "got an ipaddress for %s, using %s" % (name, pin_ipaddress)
      self.ipaddress_hash[pin_ipaddress] += 1
      ipaddress = pin_ipaddress

    self.master_port += 2  
    connections = {}
    inst = {"name": name, "path": path, "args": config, 
          "connections": connections, "master_port": self.master_port,
          "ipaddress": ipaddress}
    self.elements[self.master_port] = inst
    #random initial value
    self.loads[self.master_port] = 1000
    return inst

  def populate_shard(self, shard):
    num_elements = shard.minimum_nodes()
    shard.num_nodes = num_elements
    element_type = shard.node_type()
    self.shard_nodes[shard] = element_type
    element_name = element_type["name"]
    input_port = element_type["input_port"]
    if element_type.has_key("output_port"):
      join = self.create_element("DynamicJoin", {})
      join_port_num = self.port_num_gen.new_port()
      join.set_join_port_num(join_port_num)
      self.shard_nodes[shard]["join_node"] = join
      shard.set_join_node(join)

    for i in range(num_elements):
      output_port = "output"+str(i)
      element_config = shard.config_for_new_node()
      e = self.create_element(element_name, element_config)
      connection_port_num = self.port_num_gen.new_port()
      shard.add_port(output_port, Port.PUSH, Port.UNNAMED, [])
      shard.add_output_node_connection(output_port, connection_port_num)
      e.add_input_connection(input_port, connection_port_num)
      if element_type.has_key("output_port"):
        e.add_output_connection(element_type["output_port"], join_port_num)
        join.add_subscriber()
        
  def start_elements(self):
    for e in self.elements.values():
      print "starting " + e["name"]
      self.start_element(e)
  
  def start_element(self, element):
    config = {}
    config["name"] = element["name"]
    config["args"] = element["args"]
    config["master_port"] = self.url(element["ipaddress"], element["master_port"])
    config["ports"] = element["connections"]
    socket = self.context.socket(zmq.REQ)
    message = json.dumps(("ADD NODE", config))
    socket.connect(self.url(element["ipaddress"], 5000))
    socket.send(message)
    print "waiting for caretake to load " + element["name"]
    res = json.loads(socket.recv())
    socket.close()
    if not res:
      print "Could not start element " + element["name"]
      raise NameError
    else:
      print element["name"] + " loaded"
      
  def run(self):
    self.sync_elements()
    while True:
      try:
        self.poll_loads()
        if len(self.loads.keys()) == 0:
          print "Master: no more running nodes, quitting"
          return
        self.parallelize()
        time.sleep(4)
      except KeyboardInterrupt:
        self.stop_all()
        break
  
  def url(self, ip_address, port_number):
    return "tcp://" + ip_address + ":" + str(port_number)

  def sync_elements(self):
    for (p, e) in self.elements.items():
      self.sync_element(p, e)

  def sync_element(self, p, e):
    url = self.url(e["ipaddress"], p)
    syncclient = self.context.socket(zmq.REQ)
    syncclient.connect(url)
    print "syncing with url " + url
    syncclient.send('')
    # wait for synchronization reply
    syncclient.recv()
    syncclient.close()
  
  def timed_recv(self, socket, time):
    """time is to be given in milliseconds"""
    poller = zmq.Poller()
    poller.register(socket)
    socks = dict(poller.poll(time))
    if socks == {} or socks[socket] != zmq.POLLIN:
      return None
    else:
      return socket.recv()
    
  def poll_loads(self):
    elements = self.loads.keys()
    self.loads = {}
    for e in elements:
      load = self.poll_load(self.elements[e])
      if load != None and load != -1:
        self.loads[e] = load
  
  def poll_load(self, element):
    port = element["master_port"]
    message = json.dumps(("POLL", {}))
    socket = self.context.socket(zmq.REQ)
    socket.connect(self.url(element["ipaddress"], port))
    socket.send(message)
    #wait for 4 sec
    load = self.timed_recv(socket, 4000)
    socket.close()
    if load != None:
      load = json.loads(load)
      print "Master: %s has a load %r" % (element["name"], load)
      return load
    #element timed out
    else:
      print "** Master: %s timed out" % element["name"]
      return None

  def stop_all(self):
    print "Master: trying to stop all elements"
    raise NotImplementedError
    
  def parallelize(self):
    for e in self.loads.keys():
      if isinstance(e, Shard):
        can, config = self.can_parallelize(e)
        if can and self.num_parallel < 4:
          self.do_parallelize(e, config)
  
  def can_parallelize(self, element):
    return (False, None)
    socket = self.context.socket(zmq.REQ)
    port = element.master_port.port_number
    socket.connect(self.listen_url(port))
    message = json.dumps(("CAN ADD", {}))
    socket.send(message)
    message = self.timed_recv(socket, 8000)
    if message != None:
      return json.loads(message)
    else:
      print "Master did not get any result for parallelize from %s" % element.name
      return (False, None)
  
  def do_parallelize(self, element, config):
    print "Master: trying to parallelize %s" % element.name
    port_number = self.port_num_gen.new_port()
    print "Master: %s can parallelize with config %r, on port %r" % (element.name, config, port_number)
    node_type = self.shard_nodes[element]
    new_node = self.create_element(node_type["name"], config)
    new_node.add_input_connection(node_type["input_port"], port_number)
    if node_type.has_key("join_node"):
      join = node_type["join_node"]
      new_node.add_output_connection(node_type["output_port"], join.join_input_port.port_number)
      socket = self.context.socket(zmq.REQ)
      socket.connect(self.listen_url(join.master_port.port_number))
      message = json.dumps(("ADD JOIN", {}))
      socket.send(message)
      res = self.timed_recv(socket, 8000)
      if message == None:
        print "join node did not reply to add join, so not parallelizing"
        return      
    new_node.start()
    self.sync_element(new_node.master_port.port_number, new_node)

    socket = self.context.socket(zmq.REQ)
    port = element.master_port.port_number
    socket.connect(self.listen_url(port))
    message = json.dumps(("SHOULD ADD", {"port_number": port_number}))
    socket.send(message)
    message = self.timed_recv(socket, 8000)
    if message != None:
      print "Master: done parallelizing " + element.name
      self.num_parallel += 1
    else:
      print "Master didn't get a reply for should_add"
    
  def get_single_item(self, d):
    items = d.items()
    assert(len(items) == 1)
    return items[0]
  
  def get_or_default(self, d, key, default):
    if d.has_key(key):
      return d[key]
    else:
      d[key] = default
      return default

  def connect_node(self, from_element, from_port, to_element, to_port):
    connection_port_num = self.port_num_gen.new_port()
    connection_url = self.url(to_element["ipaddress"], connection_port_num)
    from_connections = self.get_or_default(from_element["connections"], from_port, ["output"])
    from_connections.append(connection_url)
    to_connections = self.get_or_default(to_element["connections"], to_port, ["input"])
    if len(to_connections) > 2:
      print "Cannot add multiple input connections"
      raise NameError
    to_connections.append(connection_url)
    
  def setup_connections(self, file_name):
    with open(file_name) as f:
      config = json.load(f)
    element_hash = {}
    for e in config["elements"]:
      element_id = e["id"]
      element_name = e["name"] 
      element_config = e["args"]
      element_ip = e["at"] if e.has_key("at") else None
      element = self.create_element(element_name, element_config, element_ip)
      element_hash[element_id] = element
    
    for f, t in config["connections"]:
      (from_name, from_port) = self.get_single_item(f)
      (to_name, to_port)  = self.get_single_item(t)
      from_element = element_hash[from_name]
      to_element = element_hash[to_name]
      self.connect_node(from_element, from_port, to_element, to_port)
  
if __name__ == "__main__":
  Master(sys.argv[1])