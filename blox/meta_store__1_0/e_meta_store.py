from element import *
import os
import time

class meta_store(Element):
  def on_load(self, config):
    import pymongo
    from pymongo import Connection
    
    self.name = "meta-store"
    self.config = config
    self.connection = Connection()
    self.added = []
    self.removed = []
    db = self.connection['file_metadb']
    self.file_index = db.file_index
    self.add_port("input", Port.PUSH, Port.UNNAMED, ["command", "args"])
    self.add_port("store_index", Port.PULL, Port.UNNAMED, ["command"])
    self.add_port("restore", Port.PULL, Port.UNNAMED, ["path"])
  
  def update_refs(self, path, fps):
    old_fps = list(self.file_index.find({"path": path}, {"fingerprints": 1}))
    assert(len(old_fps) <= 1)
    self.file_index.remove({"path" : path})
    if len(old_fps) > 0:
      old = set(old_fps[0]["fingerprints"])
      new = set(fps)
      self.removed.append(old - new)
      self.added.append(new - old)
  
  def recv_push(self, port, log):
    entries = []
    for command, args in log.iter_fields("command", "args"):
      if command == "ADD":
        path, fps = args
        self.update_refs(path, fps)
        entry = {"path": path, "fingerprints": fps}
        entries.append(entry)
        # print "%s: adding file %s" % (self.name, path)
      else:
        print "**%s could not understand command %s" % (self.name, command)
    
    self.file_index.insert(entries)

  def recv_pull_query(self, port, log):
    if port == "restore":
      fps = []
      for path in log.log["path"]:
        path_fps = list(self.file_index.find({"path": path}, {"fingerprints": 1}))
        assert(len(path_fps) <= 1)
        fps.append(path_fps[0]["fingerprints"])

      log.append_field("fingerprints", fps)
      self.return_pull(port, log)
    else:
      print "**%s did not implement actions on port %s" % (self.name, port)
    
  def on_shutdown(self):
    self.connection.disconnect()