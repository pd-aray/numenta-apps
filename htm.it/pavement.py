import json
import os
import pwd
import grp
import marshal
import random
import string
from collections import defaultdict
from optparse import make_option
import subprocess
import uuid
import time

from paver.easy import *
from paver.setuputils import setup
from setuptools import find_packages



version = {}

if os.path.exists("htm/it/__version__.py"):
  execfile("htm/it/__version__.py", {}, version)
else:
  exec(marshal.loads(open("htm/it/__init__.pyc").read()[8:]), {}, version)

setup_requirements = ["PyYAML", "psutil"]
install_requirements = []
dependency_links = []

with open("requirements.txt", "r") as inp:
  for line in inp:
    (lhs, delim, package) = line.strip().rpartition("#egg=")
    if lhs:
      dependency_links.append(lhs.partition("-e")[2].strip() + delim + package)
      (pkg_name, _, pkg_version) = package.partition("-")
      package = pkg_name + "==" + pkg_version
    if package.startswith("numpy"):
      setup_requirements.append(package)
    install_requirements.append(package)

setup(
  description="Project HTM-IT",
  dependency_links=dependency_links,
  install_requires=install_requirements,
  setup_requires=setup_requirements,
  name="htm.it",
  packages=find_packages(),
  include_package_data=True,
  version=version["__version__"]
)

HTM_IT_HOME = os.path.abspath(os.path.dirname(__file__))



def getOrCreateHTMITId():
  htmItIdPath = "%s/conf/.htm_it_id" % HTM_IT_HOME
  if os.path.exists(htmItIdPath):
    with open(htmItIdPath, "r") as htmItIdFile:
      return htmItIdFile.read()
  else:
    newHTMITId = uuid.uuid4().hex
    with open(htmItIdPath, "w") as htmItIdFile:
      htmItIdFile.write(newHTMITId)
    return newHTMITId



APPLICATION_CONFIG_PATH = os.path.join(HTM_IT_HOME, "conf")
SD_CONFIG_FILE = os.path.join(HTM_IT_HOME, "conf/supervisord.conf")
NGINX_CONFIG_FILE = os.path.join(HTM_IT_HOME, "conf/htm-it-api.conf")

# Baseline defaults
data = defaultdict(str)
data["APPLICATION_CONFIG_PATH"] = APPLICATION_CONFIG_PATH
data["HTM_IT_HOME"] = HTM_IT_HOME
data["HTM_IT_LOG_DIR"] = "%s/logs" % HTM_IT_HOME
data["NGINX_USER"] = pwd.getpwuid(os.getuid()).pw_name
data["NGINX_GROUP"] = grp.getgrgid(os.getgid()).gr_name
data["NGINX_SSL_CERTIFICATE"] = \
  os.path.join(HTM_IT_HOME, "conf/ssl/localhost.crt")
data["NGINX_SSL_CERTIFICATE_KEY"] = \
  os.path.join(HTM_IT_HOME, "conf/ssl/localhost.key")
data["HTM_IT_ID"] = getOrCreateHTMITId()
data["HTM_IT_UPDATE_EPOCH"] = "%f" % (time.time())
data["HTM_IT_SEND_TO_WUFOO"] = "no"
data["WUFOO_URL"] = ""
data["WUFOO_USER"] = ""
data["AWS_ACCESS_KEY_ID"] = ""
data["AWS_SECRET_ACCESS_KEY"] = ""
data["DEFAULT_EC2_REGION"] = "us-east-1"
data["NOTIFICATIONS_AWS_ACCESS_KEY_ID"] = ""
data["NOTIFICATIONS_AWS_SECRET_ACCESS_KEY"] = ""
data["NOTIFICATIONS_SENDER_EMAIL"] = ""

# Environment override
data.update(os.environ)



@task
@cmdopts([
    make_option(
      "-t",
      "--target",
      default=APPLICATION_CONFIG_PATH,
      help=("Absolute path of the directory where to store generated HTM-IT "
            "product configration files"),
      metavar="FILE")
  ])
def configure_htm_it(options):
  """ Initialize HTM-IT's baseline and long-lasting ("override") configuration
  objects
  NOTE: called by jenkins-ec2 / jenkins-ci / src / run_pipeline.py
  """
  # First, generate HTM-IT's baseline config objects
  call_task("gen_htm_it_base_config", options={"target": options.target})

  from htm.it.app import config, HTMItAppConfig

  # Delete all configuration override objects
  config.clearAllConfigOverrides()

  # Initialize HTM-IT API key
  apiKey = os.environ.get("HTM_IT_API_KEY")
  if apiKey is None:
    apiKey = "".join(
      random.choice("".join(set(string.letters + string.digits) - set('1iLl0Oo')))
      for _ in xrange(5))

  config = HTMItAppConfig(mode=HTMItAppConfig.MODE_OVERRIDE_ONLY)
  config.add_section("security")
  config.set("security", "apikey", apiKey)
  config.save()



@task
@cmdopts([
    make_option(
      "-t",
      "--target",
      default=APPLICATION_CONFIG_PATH,
      help=("Absolute path of the directory where to store generated HTM-IT "
            "product configration files"),
      metavar="FILE")
  ])
def gen_htm_it_base_config(options):
  """ (Re)generate HTM-IT's baseline configuration objects """

  def generateConf(baseName, targetDir):
    # Read the template file
    with open(os.path.join("conf", baseName + ".tpl"), "r") as src:
      tpl = src.read()

      # Create the .conf file by applying substitutions from the data dict
      with open(os.path.join(targetDir, baseName + ".conf"), "w") as outp:
        outp.write(tpl % data)

  generateConf("application", options.target)
  generateConf("model-swapper", options.target)
  generateConf("model-checkpoint", options.target)
  generateConf("product", options.target)
  generateConf("quota", options.target)

  print
  print "HTM-IT product configuration files created at", options.target
  print "For development purposes, be sure to set APPLICATION_CONFIG_PATH in ",
  print "your environment:"
  print
  print "    export APPLICATION_CONFIG_PATH=%s" % options.target
  print
  print "Also consider setting HTM_IT_API_KEY.  If a value exists in your ",
  print "environment, it will be used, otherwise a new one will be generated ",
  print "every time your configuration is created"
  print



@task
@cmdopts([
    make_option(
      "-t",
      "--target",
      default=NGINX_CONFIG_FILE,
      help="Target file",
      metavar="FILE")
  ])
def configure_nginx(options):
  """ Create HTM-IT nGinx file """

  with open("conf/htm-it-api.tpl", "r") as src:
    tpl = src.read()

    with open(options.target, "w") as outp:
      outp.write(tpl % data)

    print
    print "nGinx configuration file created at", options.target
    print "To start nGinx, run this command:"
    print
    print "    sudo nginx -p . -c", options.target
    print



@task
@cmdopts([
    make_option(
      "-t",
      "--target",
      default=SD_CONFIG_FILE,
      help="Target file",
      metavar="FILE")
  ])
def configure_supervisord(options):
  """ Create HTM-IT supervisord configuration file """

  with open("conf/supervisord.tpl", "r") as src:
    tpl = src.read()

    with open(options.target, "w") as outp:
      outp.write(tpl % data)

    print
    print "supervisord configuration file created at", options.target
    print "To start supervisord, run this command:"
    print
    print "    supervisord -c", options.target
    print



@task
def init_htm_itdb():
  """ Initialize HTM-IT database """
  if "APPLICATION_CONFIG_PATH" not in os.environ:
    os.environ["APPLICATION_CONFIG_PATH"] = data["APPLICATION_CONFIG_PATH"]

  import htm.it.app.repository

  htm.it.app.repository.reset()



@task
def clean_rabbitmq():
  """ Initialize RabbitMQ Queues """
  if "APPLICATION_CONFIG_PATH" not in os.environ:
    os.environ["APPLICATION_CONFIG_PATH"] = data["APPLICATION_CONFIG_PATH"]

  from nta.utils.amqp.connection import RabbitmqConfig
  rabbitmq_config = RabbitmqConfig()
  rabbitmq_user = rabbitmq_config.get("credentials", "user")
  rabbitmq_password = rabbitmq_config.get("credentials", "password")

  # List HTM-IT queues
  result = subprocess.check_output(["rabbitmqadmin",
                                    "--host=rabbit",
                                    "--username=%s" % rabbitmq_user,
                                    "--password=%s" % rabbitmq_password,
                                    "list",
                                    "queues",
                                    "name",
                                    "--format=raw_json"])

  # Delete queues individually
  for queue in json.loads(result):
    if (queue["name"].startswith("htm.it.") or
        queue["name"] == "notifications"):

      subprocess.check_call(["rabbitmqadmin",
                             "--host=rabbit",
                             "--username=%s" % rabbitmq_user,
                             "--password=%s" % rabbitmq_password,
                             "delete",
                             "queue",
                             "name=%(name)s" % queue])
      print queue["name"], "queue deleted."

  # List HTM-IT exchanges
  result = subprocess.check_output(["rabbitmqadmin",
                                    "--host=rabbit",
                                    "--username=%s" % rabbitmq_user,
                                    "--password=%s" % rabbitmq_password,
                                    "list",
                                    "exchanges",
                                    "name",
                                    "--format=raw_json"])

  # Delete exchanges individually
  for exchange in json.loads(result):
    if exchange["name"].startswith("htm.it."):
      subprocess.check_call(["rabbitmqadmin",
                             "--host=rabbit",
                             "--username=%s" % rabbitmq_user,
                             "--password=%s" % rabbitmq_password,
                             "delete",
                             "exchange",
                             "name=%(name)s" % exchange])
      print exchange["name"], "exchange deleted."



@task
def clean_checkpoints():
  """ Clear old model checkpoints """
  from htmengine.model_checkpoint_mgr import model_checkpoint_mgr

  model_checkpoint_mgr.ModelCheckpointMgr.removeAll()



@task
def gen_base_configs():
  """ (Re)generate baseline configuration objects for all subsystems """
  call_task("configure_supervisord", options={"target": SD_CONFIG_FILE})
  call_task("configure_nginx", options={"target": NGINX_CONFIG_FILE})
  call_task("gen_htm_it_base_config", options={"target": APPLICATION_CONFIG_PATH})



@task
def init():
  """Perform all necessary initialization."""
  call_task("configure_supervisord", options={"target": SD_CONFIG_FILE})
  call_task("configure_nginx", options={"target": NGINX_CONFIG_FILE})
  call_task("configure_htm_it", options={"target": APPLICATION_CONFIG_PATH})
  call_task("init_htm_itdb")
  call_task("clean_rabbitmq")
  call_task("clean_checkpoints")
