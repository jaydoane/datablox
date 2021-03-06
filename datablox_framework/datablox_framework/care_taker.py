import zmq
import json
import os
import os.path
import sys
import subprocess
import signal
from optparse import OptionParser
from fileserver import file_server_keypath
import string
import logging

logger = logging.getLogger(__name__)

import naming

try:
  import datablox_engage_adapter.file_locator
  using_engage = True
except ImportError:
  using_engage = False

if using_engage:
  engage_file_locator = datablox_engage_adapter.file_locator.FileLocator()
  import datablox_engage_adapter.install
else:
  engage_file_locator = None


processes = []
fileserver_process = None
socket = None

def stop_all():
  logger.info("[caretaker] stopping all blocks")
  for p in processes:
    p.terminate()
  logger.info("[caretaker] done")

def shutdown():
  stop_all()
  if fileserver_process:
    fileserver_process.terminate()
  socket.close()
  sys.exit(0)
  
def sigterm_handler(signum, frame):
  logger.info("[caretaker] got SIGTERM")
  shutdown()

def start_fileserver():
  global fileserver_process
  
  #with open(file_server_keypath, 'w') as f:
  #  f.write(gen_random(8))

  fileserver_script = os.path.join(os.path.dirname(__file__),
                                   "fileserver.py")
  command = [sys.executable, fileserver_script]
  fileserver_process = subprocess.Popen(command)
    
def main(argv):
  global processes, socket

  # setup logging
  root_logger = logging.getLogger()
  if len(root_logger.handlers)==0:
    console_handler = logging.StreamHandler(sys.stdout)
    if using_engage:
      log_level = logging.DEBUG # stdout is going to a file anyway
    else:
      log_level = logging.INFO
    console_handler.setLevel(log_level)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(log_level)

  usage = "%prog [options]"
  parser = OptionParser(usage=usage)
  parser.add_option("-b", "--bloxpath", dest="bloxpath", default=None,
                    help="use this path instead of the environment variable BLOXPATH")
  parser.add_option("--config-dir", dest="config_dir", default=".",
                    help="directory to use for storing configuration files for the individual blocks")
  parser.add_option("--log-dir", dest="log_dir", default=None,
                     help="Directory to use for log files, if not specified just use the console")

  (options, args) = parser.parse_args(argv)

  signal.signal(signal.SIGTERM, sigterm_handler)
  bloxpath = options.bloxpath
  
  if bloxpath == None: 
    if not os.environ.has_key("BLOXPATH"):
      parser.error("Need to set BLOXPATH environment variable or pass it as an argument")
    else:
      bloxpath = os.environ["BLOXPATH"]

  if not os.path.isdir(bloxpath):
    parser.error("BLOXPATH %s does not exist or is not a directory" % bloxpath)

  config_dir = os.path.abspath(os.path.expanduser(options.config_dir))
  if not os.path.isdir(config_dir):
    parser.error("Configuration file directory %s does not exist or is not a directory" % config_dir)
  if options.log_dir:
    log_dir = os.path.abspath(os.path.expanduser(options.log_dir))
    if not os.path.isdir(log_dir):
      try:
        os.makedirs(log_dir)
      except:
        parser.error("Log directory %s does not exist and attempt at creating it failed" % log_dir)
  else: # log_dir was not specified, use stdout
    log_dir = None

  logger.info("Caretaker starting, BLOXPATH=%s, using_engage=%s" %
              (bloxpath, using_engage))
  if not using_engage:
    start_fileserver()
  context = zmq.Context()
  socket = context.socket(zmq.REP)
  socket.bind('tcp://*:5000')
  os.system("rm %s/*.json" % config_dir)
  file_num = 0
  logger.info('Care taker loaded')
  while True:
    try:
      message = socket.recv()
      control_data = json.loads(message)
      logger.info("[caretaker] received msg: " + message)
      control, data = control_data
      if control == "ADD NODE":
        try:
          if using_engage:
            block_name = data["name"]
            block_version = data["version"] if data.has_key("version") \
                            else naming.DEFAULT_VERSION
            resource_key = naming.get_block_resource_key(block_name,
                                                         block_version)
            logger.info("Using engage to install resource %s" % resource_key)
            datablox_engage_adapter.install.install_block(resource_key)
            logger.info("Install of %s and its dependencies successful" % \
                        resource_key)
          config_name = os.path.join(config_dir,
                                     data["name"] + str(file_num) + ".json")
          file_num += 1
          with open(config_name, 'w') as config_file:
            json.dump(data, config_file)
          load_block_script = os.path.join(os.path.dirname(__file__),
                                           "load_block.py")
          command = [sys.executable, load_block_script, bloxpath, config_name]
          if log_dir:
            command.append(log_dir)
          logger.debug("Running command %s" % command)
          p = subprocess.Popen(command)
          processes.append(p)
        except Exception, e:
          logger.exception("Got exception %s when processing ADD NODE message" % e)
          socket.send(json.dumps(False))
          continue
        socket.send(json.dumps(True))
      elif control == "STOP ALL":
        stop_all()
        processes = []
        socket.send(json.dumps(True))
      else:
        logger.info("[caretaker] **Warning could not understand master")
    except KeyboardInterrupt:
      logger.info("[caretaker] Stopping care_taker")
      break
          
  shutdown()

def call_from_console_script():
    main(sys.argv[1:])

if __name__ == "__main__":
  main(sys.argv[1:])
