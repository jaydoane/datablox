from element import *
import time
import base64

class dump(Element):
  def on_load(self, config):
    self.name = "Dump"
    self.config = config
    self.add_port("input", Port.PUSH, Port.UNNAMED, [])
    self.sleep_time = config["sleep"] if config.has_key("sleep") else 0
    self.keys = config["decode_fields"] if config.has_key("decode_fields") else []
    print "Dump element loaded"

  def decode_fields(self, log):
    for key in self.keys:
      if not log.log.has_key(key):
        continue
      else:
        values = log.log[key]
        values_decoded = [base64.b64decode(v) for v in values]
        log.append_field(key, values_decoded)
  
  def recv_push(self, port, log):
    self.decode_fields(log)
    print "log is: " + str(log.log)
    time.sleep(self.sleep_time)