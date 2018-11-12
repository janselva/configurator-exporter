'''
discover services
'''
import os
import subprocess
import re
import psutil
from config_handler import configurator
from common.util import *

logger = expoter_logging(COLLECTD_MGR)
SERVICE_NAME = {
    "elasticsearch": "ES",
    "apache": "apache",
    "mysql": "mysql",
    "mssql": "mssql",
    "postgres": "postgres",
    "nginx": "nginx",
    "tpcc": "tpcc",
    "kafka.Kafka": "kafka",
    "zookeeper": "zookeeper",
    "hxconnect": "hxconnect",
    "cassandra": "cassandra",
    "knox": "knox",
    "esalogstore": "ESAlogstore"
}
SERVICES = [
    "elasticsearch",
    "apache",
    "mysql",
    "mssql",
    "postgres",
    "nginx",
    "tpcc",
    "kafka.Kafka",
    "zookeeper",
    "hxconnect",
    "cassandra",
    "knox",
    "esalogstore"
]
'''
Mapping for services and the plugin to be configured for them.
'''
SERVICE_PLUGIN_MAPPING = {
    "elasticsearch": "elasticsearch",
    "apache": "apache",
    "mysql": "mysql",
    "mssql": "mssql",
    "postgres": "postgres",
    "nginx": "nginx",
    "tpcc": "tpcc",
    "kafka.Kafka": "kafkatopic",
    "zookeeper": "zookeeperjmx",
    "hxconnect": "hxconnect",
    "knox": "oozie",
    "cassandra": "cassandra"
}

POLLER_PLUGIN = ["elasticsearch"]

def add_pid_usage(pid, pid_list):
    """Add usage stats of each pids"""

    pid_detail = psutil.Process(pid)
    if not pid_detail.is_running():
        return
    pid_info = {}
    pid_info["user"] = pid_detail.username()
    pid_info["process_id"] = pid
    pid_info["cpuUsage"] = pid_detail.cpu_percent()
    pid_info["memUsage"] = pid_detail.memory_percent()
    pid_info["status"] = "running"
    pid_list.append(pid_info)


def check_jmx_enabled(pid):
    """Check if jmx enabled for java process"""
    pid_detail = psutil.Process(pid)
    if re.search("Dcom.sun.management.jmxremote", str(pid_detail.cmdline())):
        return True
    return False


def get_process_id(service):
    '''
    :param service: name of the service
    :return: return a list of PID's assosciated with the service along with their
    status, memUsage, cpuUsage and user
    '''
    logger.info("Get process id for service %s", service)
    pids = []

    if service in ["kafka.Kafka", "zookeeper"]:
        try:
            # Common logic for jmx related process
            process_ids = []
            java_avail = subprocess.check_call(
                ["java", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if not java_avail:
                jcmd = subprocess.Popen(
                    "jcmd | awk '{print $1 \" \" $2}' | grep -w \"%s\"" %
                    service, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                res, err = jcmd.communicate()
                if not res:
                    j_pids = res.splitlines()
                    for j_pid in j_pids:
                        if not j_pid:
                            pidval = j_pid.split()
                            if check_jmx_enabled(pidval[0]):
                                process_ids.append(pidval[0])

            for procid in process_ids:
                add_pid_usage(procid, pids)
            logger.info("PIDs %s", pids)
            return pids
        except BaseException:
            logger.info("PIDs %s", pids)
            return pids

    try:
        if service == "apache":
            os_cmd = "lsb_release -d"
            proc_out = subprocess.Popen(
                os_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True)
            (out, err) = proc_out.communicate()
            for line in out.splitlines():
                if "Ubuntu" in line:
                    service = "apache2"
                    break
            # The linux flavour is not Ubuntu could be CentOS or redHat so
            # search for httpd
            if service == "apache":
                service = "httpd"

        process_id = ""
        for proc in psutil.process_iter(attrs=['pid', 'name', 'username']):
            # Java processes
            if service in ["elasticsearch", "cassandra", "knox"]:
                if proc.info.get("name") == "java" and proc.info.get(
                        "username") == service:
                    process_id = proc.info.get("pid")
                    break
            # Postgres process
            elif service in ["postgres"]:
                if proc.info.get("name") == "postmaster" or proc.info.get(
                        "name") == "postgres":
                    process_id = proc.info.get("pid")
                    break
            # Non java processes
            elif service in str(proc.info.get("name")):
                process_id = proc.info.get("pid")
                break

        add_pid_usage(process_id, pids)
        logger.info("PIDs %s", pids)
        return pids
    except BaseException:
        logger.info("PIDs %s", pids)
        return pids


def add_status(proc_dict):
    '''
    Find the status of the PID running, sleeping.
    :param dict: dictionary return by get_process_id
    :return: add status for the PID in th dictionary.
    '''
    # Add state, threads assosciated with the service PID
    fileobj = open('/proc/%d/status' % (proc_dict["PID"]))
    if not fileobj:
        return None
    lines = fileobj.readlines()
    for line in lines:
        if line.startswith("State:"):
            state = (line.split())[2]
            state = state.strip("()")
            proc_dict["state"] = state
        elif line.startswith("Threads:"):
            threads = line.split()
            threads = threads[1]
            proc_dict["threads"] = threads
    return proc_dict


def add_ports(service_dict, service):
    '''
    Add listening ports for the PID
    :param dict: dictionary returned by add_status
    :param service: name of the service
    :return: add listening ports for the PID to the dictionary
    '''
    logger.debug("Add ports %s %s", service_dict, service)
    ports = []
    if service == "apache":
        apache_service = ""
        os_cmd = "lsb_release -d"
        proc_out = subprocess.Popen(
            os_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True)
        (out, err) = proc_out.communicate()
        for line in out.splitlines():
            if "Ubuntu" in line:
                apache_service = "apache2"
                break
        if apache_service == "":
            apache_service = "httpd"
        cmd = "netstat -anp | grep %s" % (apache_service)
    else:
        cmd = "netstat -anp | grep %s" % (service_dict["PID"])
    proc_out = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True)
    (out, err) = proc_out.communicate()
    for line in out.splitlines():
        line = line.split()
        if((line[5] == 'LISTEN') and (service == "apache" or str(service_dict['PID']) in line[6])):
            port = (line[3].split(':')[-1])
            if port not in ports:
                ports.append(port)
    service_dict['ports'] = ports
    return service_dict


def add_logger_config(service_dict, service):
'''
    Add logger config
'''
    service_dict["loggerConfig"] = []
    fluentd_plugins = configurator.get_fluentd_plugins_mapping().keys()
    for item in fluentd_plugins:
        if item.startswith(service.split(".")[0]):
            log_config = {}
            log_config["name"] = item
            log_config["config"] = {}
            log_config["config"]["filters"] = {}
            service_dict["loggerConfig"].append(log_config)
    return service_dict


def add_poller_config(service, service_dict):
'''
    Add poller config
'''
    service_dict["pollerConfig"] = {}
    poller_config = {}
    poller_config["config"] = {}

    for key, value in SERVICE_PLUGIN_MAPPING.items():
        if key == service:
            poller_config["name"] = value
            break

    config = configurator.get_metrics_plugins_params(poller_config["name"])
    for item in config["plugins"]:
        if item.get("config") and item.get("name") == poller_config["name"]:
            for item1 in item["config"]:
                poller_config["config"][item1["fieldName"]] = item1["defaultValue"]
    service_dict["pollerConfig"].update(poller_config)

    return service_dict


def add_agent_config(service, service_dict):
    '''
    Find the input config for the plugin fieldname:defaultvalue
    :param service: name of the service
    :param dict: poller_dict as the input
    :return:
    '''
    service_dict["agentConfig"] = {}
    agent_config = {}
    agent_config["config"] = {}
    for key, value in SERVICE_PLUGIN_MAPPING.items():
        if key == service:
            agent_config["name"] = value
            break
    config = configurator.get_metrics_plugins_params(agent_config["name"])
    for item in config["plugins"]:
        if item.get("config") and item.get("name") == agent_config["name"]:
            # Config specific to jvm plugin
            if agent_config["name"] == "jvm":
                agent_config["config"]["process"] = service
                break
            if agent_config["name"] == "kafkatopic":
                agent_config["config"]["process"] = service
                for parameter in item["config"]:
                    agent_config["config"][parameter["fieldName"]] = parameter["defaultValue"]
                break
            for parameter in item["config"]:
                agent_config["config"][parameter["fieldName"]] = parameter["defaultValue"]

    # In apache plugin replace the port default value with the listening ports for apache/httpd,
    # if there are multiple listening ports for the PID assosciate the first
    # port with the PID
    if service == "apache":
        if len(service_dict["ports"]) != 0:
            agent_config["config"]["port"] = service_dict["ports"][0]
            if agent_config["config"]["port"] == "443":
                agent_config["config"]["secure"] = "true"

    service_dict["agentConfig"].update(agent_config)
    return service_dict


def discover_services():
    '''
    Find the services which are running on the server and return it's PID list, users, CPUUsage,
    memUsage, Listening ports, input configuration for the plugin.
    :return:
    '''
    logger.info("Discover service started")
    discovery = {}
    for service in SERVICES:
        if (service == "tpcc" and os.path.exists("/opt/VDriver/.tpcc_discovery")) or \
                (service == "hxconnect" and os.path.exists("/opt/VDriver/.hxconnect_discovery")):
            port_dict = {}
            port_dict["loggerConfig"] = []
            port_dict["agentConfig"] = {}
            final_dict = add_agent_config(service, port_dict)
            discovery[SERVICE_NAME[service]] = []
            discovery[SERVICE_NAME[service]].append(final_dict)
        elif service == "esalogstore" and os.path.exists("/opt/esa_conf.json"):
            port_dict["loggerConfig"] = []
            port_dict["agentConfig"] = {}
            final_dict = add_logger_config(port_dict, service)
            discovery[SERVICE_NAME[service]] = []
            discovery[SERVICE_NAME[service]].append(final_dict)

        pid_list = get_process_id(service)
        if not pid_list:
            continue
        discovery[SERVICE_NAME[service]] = []
        for item in pid_list:
            service_pid_dict = {}
            service_pid_dict["PID"] = []
            service_pid_dict["PID"] = item["process_id"]

            # Add PID, cpuUsage, memUsage, status to service_discovery
            service_pid_dict["PID"] = item["process_id"]
            service_pid_dict["user"] = item["user"]
            service_pid_dict["cpuUsage"] = item["cpuUsage"]
            service_pid_dict["memUsage"] = item["memUsage"]
            service_pid_dict["status"] = item["status"]

            # Add state, threads assosciated with the service PID
            status_dict = add_status(service_pid_dict)

            # Add listening ports assosciated with the service PID
            port_dict = add_ports(status_dict, service)

            if service in POLLER_PLUGIN:
                port_dict["loggerConfig"] = []
                port_dict["agentConfig"] = {}
                final_dict = add_poller_config(service, port_dict)
            else:
                logger_dict = add_logger_config(port_dict, service)
                logger_dict["pollerConfig"] = {}
                final_dict = add_agent_config(service, logger_dict)

            discovery[SERVICE_NAME[service]].append(final_dict)
    logger.info("Discovered service %s", discovery)
    return discovery
