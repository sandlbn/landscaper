# Copyright (c) 2017, Intel Research and Development Ireland Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import requests
import xml.etree.ElementTree as Et
from landscaper.collector import base
from landscaper.common import LOG
from landscaper import paths
from landscaper.utilities import configuration
import urllib3
requests.packages.urllib3.disable_warnings()

CONFIG_SECTION_GENERAL = 'general'
CONFIG_CIMI_URL = "cimi_url"

CONFIG_SECTION_PHYSICAL = 'physical_layer'
CONFIG_VARIABLE_MACHINES = 'machines'

MF2C_PATH_VALUE = "mf2c_device_id"

EVENTS = ['cimi.device.add', 'cimi.device.delete']

class CimiPhysicalCollector(base.Collector):
    """
    Physical Layer collector that queries CIMI for hwloc and cpu_info files and
    saves files in the Data Directory.
    """
    def __init__(self, graph_db, conf_manager, events_manager, events=None):
        if not events_manager:
            Events = None
        else:
            Events = EVENTS
        super(CimiPhysicalCollector, self).__init__(graph_db, conf_manager, events_manager, events=Events)
        self.cnf = conf_manager

    def init_graph_db(self):
        """
        Retrieve hwloc and cpu_info for each machine and add
        files to the Data Directory.
        """
        LOG.info("Generating hwloc and cpu_info files")
        for device in self.get_devices():
            self.generate_files(device)

    def update_graph_db(self, event, body):
        """
        Save the hwloc and cpuinfo files to be picked up by the physical collector.
        """
        if event=='cimi.device.add':
            device = self.get_device(body)
            self.generate_files(device)

        elif event == 'cimi.device.delete':
            self.delete_files(body)

    def generate_files(self, device):
        """
        Queries the hwloc and cpuinfo methods and writes them to a file
        :param device: CIMI Device object containing hwloc and cpu_info methods
        :return: True if file successfully saved and hostname, False if errors encountered
        """
        hostname = ""
        try:
            hwloc = device["hwloc"]
            if hwloc is None:
                LOG.error(
                    "hwLoc data has not been set for this device: " + device.id + ". No HwLoc file will be saved.")
                return False

            cpu_info = device["cpuinfo"]
            if cpu_info is None:
                LOG.error(
                    "CPU_info data has not been set for this device: " + device.id + ". No CPU_info file will be saved.")
                return False

            hwloc, hostname = self._parse_hwloc(device, hwloc)

            # save the cpu info to file
            cpu_path = os.path.join(paths.DATA_DIR, hostname + "_cpuinfo.txt")
            self._write_to_file(cpu_path, cpu_info)

            # save the hwloc to file
            hwloc_path = os.path.join(paths.DATA_DIR, hostname + "_hwloc.xml")
            self._write_to_file(hwloc_path, hwloc)

        except Exception as ex:
            LOG.error("General Error hwloc/cpuinfo for device: {} - Error message: {}".format(device['id'], ex.message))
            return False, None
        return True, hostname

    # deletes hwloc & cpuinfo files for a device.
    def delete_files(self, device):
        try:
            hwloc = device["hwloc"]
            hwloc, hostname = self._parse_hwloc(device, hwloc)
            hwloc_path = os.path.join(paths.DATA_DIR, hostname + "_hwloc.xml")
            cpu_path = os.path.join(paths.DATA_DIR, hostname + "_cpuinfo.txt")
            os.remove(hwloc_path)
            os.remove(cpu_path)
        except Exception as ex:
            LOG.error("Error deleting hwloc/cpuinfo for device: {}, Error message:{}".format(device['id'], ex.message))

    # returns all instances of devices
    def get_devices(self):
        #try:
        cimi_url = self.cnf.get_variable(CONFIG_SECTION_GENERAL, CONFIG_CIMI_URL)
        if cimi_url is None:
            LOG.error("'CIMI_URL' has not been set in the 'general' section of the config file")
            return
        res = requests.get(cimi_url + '/device',
                           headers={'slipstream-authn-info': 'internal ADMIN'},
                           verify=False)

        if res.status_code == 200:
            return res.json()['devices']

        LOG.error("Request failed: " + res.status_code)
        LOG.error("Response: " + str(res.json()))
        return dict()
        # except Exception as ex:
        # LOG.error('Exception', ex.message)
        # return dict()

    # returns a specific device
    def get_device(self, device_id):
        #try:
        cimi_url = self.cnf.get_variable(CONFIG_SECTION_GENERAL, CONFIG_CIMI_URL)
        if cimi_url is None:
            LOG.error("'CIMI_URL' has not been set in the 'general' section of the config file")
            return
        res = requests.get(cimi_url + '/' + device_id,
                           headers={'slipstream-authn-info': 'internal ADMIN'},
                           verify=False)

        if res.status_code == 200:
            return res.json()

        LOG.error("Request failed: " + str(res.status_code))
        LOG.error("Response: " + str(res.json()))
        return dict()
        # except Exception as ex:
        # LOG.error('Exception', ex.message)
        # return dict()

    def _parse_hwloc(self, device, hwloc_str):
        doc_root = Et.fromstring(hwloc_str)
        device_id = device["id"][7:]  # eg, device/737fe63b-2a34-44fe-9177-3aa6284ba2f5#
        for child in doc_root:
            if child.tag == "object" and child.attrib["type"] == "Machine":
                # get hostname
                for info in child.iter("info"):
                    if info.attrib["name"] == "HostName":
                        hostname = info.attrib["value"]
                        break

                # add mf2c device id to hwloc file
                device_id_att = dict()
                device_id_att["name"] = MF2C_PATH_VALUE
                device_id_att["value"] = device_id
                Et.SubElement(child, "info", device_id_att)

                # add device's ip address to the hwloc file
                if device["ethernetAddress"]:
                    ipaddress = self._get_ipaddress(device["ethernetAddress"])
                    ipaddress_att = dict()
                    ipaddress_att["name"] = "ipaddress"
                    ipaddress_att["value"] = ipaddress
                    Et.SubElement(child, "info", ipaddress_att)

                hwloc = Et.tostring(doc_root)
                break
        return hwloc, hostname,

    def _get_ipaddress(self, input_string):
        """
        Extracts the first instance of address from the supplied param
        :param input_string: assumes the following format: "[snic(family=<AddressFamily.AF_INET: 2>,
                address='172.17.0.3', netmask='255.255.0.0', broadcast='172.17.255.255', ptp=None),
                snic(family=<AddressFamily.AF_PACKET: 17>, address='02:42:ac:11:00:03', netmask=None,
                broadcast='ff:ff:ff:ff:ff:ff', ptp=None)]"
        :return: string
        """
        ip_address = None
        arr = input_string.split(",")
        for item in arr:
            tmparr = item.split("=")
            if tmparr.__len__() > 1:
                if tmparr[0].strip() == "address":
                    ip_address = tmparr[1]
                    break
        # strip leading/ending quotes
        return ip_address[1:-1]
 
    @staticmethod
    def _write_to_file(filename, file_content):
        """
        Creates file, writes to file, saves  and closes file
        :param filename: file name including file path
        :param file_content: string content for file
        """
        file_handler = open(filename, "w")
        file_handler.write(file_content)
        file_handler.close()

if __name__ == "__main__":
    # from landscaper.utilities import configuration
    conf_manager = configuration.ConfigurationManager()
    conf_manager.add_section('physical_layer')
    conf_manager.add_section('general')

    dut = CimiPhysicalCollector(None, conf_manager,None, None)
    LOG.info(dut.init_graph_db())
