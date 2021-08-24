#!/usr/bin/env python3

# pymotdstats, a dynamic message of the day written in python
# Copyright (C) 2021  Matthieu Petiot
# https://github.com/ardeidae/pymotdstats
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import configparser
import glob
import os
import re
import time
from enum import Enum, unique
from subprocess import check_output, CalledProcessError


VERSION = '1.1.0'
INI_FILE = '/etc/pymotdstats.ini'

UNKNOWN = 'Unknown'
UNKNOWN_ADDRESS = 'Unknown address'
UNKNOWN_UPTIME = 'Unknown uptime'


@unique
class Protocol(Enum):
    """ This Enum stores tcp, udp, tcp6 or udp6 values. """

    TCP = 'tcp'
    TCP6 = 'tcp6'
    UDP = 'udp'
    UDP6 = 'udp6'

    @classmethod
    def from_value(cls, _value):
        """ Get Protocol Enum from its value.

        :type _value: str
        :param _value: a value of Protocol
        :rtype: Protocol
        :return: Protocol Enum
        """
        if type(_value) == str:
            for p in cls:
                if p.value == _value:
                    return p
        return None

    def __lt__(self, other):
        return self.value < other.value

    def __eq__(self, other):
        return self.value == other.value

    def __hash__(self):
        return hash(self.value)


class TermColor:
    """ Some Terminal Colors and styles. """

    bold = '\033[1m'
    reset = '\033[0m'
    red = '\033[91m'
    green = '\033[92m'
    orange = '\033[93m'
    blue = '\033[94m'


def get_config(_ini_file):
    """ Get a setting dict from an ini file.

    :type _ini_file: str
    :param _ini_file: the path to ini file
    :rtype: dict
    :return: the settings dict
    """

    config = dict()

    if os.path.isfile(_ini_file):
        parser = configparser.RawConfigParser()
        try:
            parser.read(_ini_file)
            sections = parser.sections()
            for s in ('display', 'threshold'):
                if s in sections:
                    for k in parser[s]:
                        try:
                            config[k] = int(parser[s][k].strip())
                        except ValueError:
                            config[k] = None

            for s in ('disk', 'services'):
                if s in sections:
                    for k in parser[s]:
                        stripped = map(str.strip, parser[s][k].split(','))
                        config[k] = set(filter(lambda x: x, stripped))

            s = 'ports'
            if s in sections:
                for k in parser[s]:
                    try:
                        stripped = map(str.strip, parser[s][k].split(','))
                        config[k] = set(map(int, filter(lambda x: x, stripped)))
                    except ValueError:
                        config[k] = set()
        except configparser.Error:
            # nothing to do
            pass

    return config


def get_hostname():
    """ Get the hostname, or Unknown.

    :rtype: str
    :return: the hostname
    """

    try:
        return check_output('hostname', encoding='utf8').strip()
    except FileNotFoundError:
        return UNKNOWN


def get_uptime():
    """ Get the uptime, or Unknown uptime.

    :rtype: str
    :return: the uptime
    """

    try:
        return check_output(['uptime', '-p'], encoding='utf8').strip()
    except FileNotFoundError:
        return UNKNOWN_UPTIME


def get_default_iface():
    """ Return the default network interface. The one where our default route
    is. If it cannot be found, return None.

    :rtype: str
    :return: the interface
    """

    try:
        with open('/proc/net/route') as file_:
            for line in file_.readlines():
                word = line.split()
                # default destination must be '00000000'
                if word[1] == '00000000':
                    return word[0]
    except FileNotFoundError:
        # nothing to do
        pass

    return None


def get_ip(_iface):
    """ Find the local ip address for the given device.

    :type _iface: str
    :param _iface: the given interface
    :rtype: str
    :return: the IP address, or 'Unknown address'
    """

    if _iface is None:
        return UNKNOWN_ADDRESS
    try:
        cmd = ('ip', 'route', 'list', 'dev', _iface)
        for line in check_output(cmd, encoding='utf8').strip().split('\n'):
            last_word = ''
            for word in line.split():
                if last_word == 'src':
                    return word
                last_word = word
    except FileNotFoundError:
        # nothing to do
        pass
    return UNKNOWN_ADDRESS


def get_load():
    """ Get the load average for 1, 5, and 15 minutes as a dictionary. Values
    can be 'Unknown'.

    :rtype: str
    :return: the load
    """

    load = dict()
    try:
        with open('/proc/loadavg') as file_:
            line = file_.read()
            array = line.split()
            load['1min'] = float(array[0])
            load['5min'] = float(array[1])
            load['15min'] = float(array[2])
    except FileNotFoundError:
        load['1min'] = UNKNOWN
        load['5min'] = UNKNOWN
        load['15min'] = UNKNOWN
    return load


def get_processes():
    """ Get the number of running processes.

    :rtype: int
    :return: the number of running processes
    """

    return len(glob.glob('/proc/[0-9]*'))


def get_users():
    """ Get the connected users on the system as a set.

    :rtype: set
    :return: set of connected users
    """

    users = set()
    try:
        for line in check_output('who', encoding='utf8').strip().split('\n'):
            array = line.split()
            if len(array) > 0:
                users.add(array[0])
    except FileNotFoundError:
        # nothing to do
        pass
    return users


def get_mount_points():
    """ Get the file system mount points as a set.

    :rtype: set
    :return: the mount points
    """

    ignore_words = ('debugfs', 'devpts', 'proc', 'sysfs', 'tmpfs')
    mount_points = set()
    pattern = re.compile(r'^\s*#')
    try:
        with open('/etc/fstab') as file_:
            for line in file_:
                if not pattern.match(line):
                    array = line.split()
                    if len(array) >= 2:
                        if array[0] not in ignore_words and array[2] != 'swap':
                            mount_points.add(array[1])
    except FileNotFoundError:
        # nothing to do
        pass
    return mount_points


def get_disk_space(_mount_points, _exclude):
    """ Get disk space for each mount point.

    :type _mount_points: set
    :param _mount_points, a set of mount points for which we want disk space.
    :type _exclude: set
    :param _exclude, a set of mount points to exclude from results.
    :rtype: dict
    :return a dictionary whose key is the mount point, and the value is another
    dictionary whose keys are used space in percent and available space.
    """

    results = dict()
    try:
        if type(_mount_points) is set:
            cmd = ('df', '-h')
            for line in check_output(cmd, encoding='utf8').strip().split('\n'):
                array = line.split()
                if array[5] in _mount_points and array[5] not in _exclude:
                    result = dict()
                    result['use%'] = int(array[4][:-1])
                    result['available'] = array[3]
                    results[array[5]] = result
    except FileNotFoundError:
        # nothing to do
        pass

    return results


def get_meminfo():
    """ Get memory information as a dictionary: free mem, total mem, free swap,
    total swap, buffers, cached, reclaimable.

    :rtype: dict
    :return: the memory information
    """

    meminfo = dict()
    keys = ('MemFree', 'MemTotal', 'SwapFree', 'SwapTotal',
            'Buffers', 'Cached', 'SReclaimable')
    try:
        with open('/proc/meminfo') as file_:
            for line in file_.readlines():
                key, size = map(str.strip, line.split(':'))
                if key in keys:
                    meminfo[key] = int(size.split()[0])
    except FileNotFoundError:
        # nothing to do
        pass
    return meminfo


def get_listening_ports():
    """ Get a set of pairs (listening port and protocol).

    :rtype: set
    :return: a set of pairs of listening ports and protocol
    """

    listening_ports = set()

    try:
        with open(os.devnull, 'w') as devnull:
            cmd = ('netstat', '-nlp')
            for line in check_output(cmd, stderr=devnull,
                                     encoding='utf8').strip().split('\n'):
                array = line.split()

                proto = array[0]
                current_port = array[3].split(':')[-1]

                if proto in ('tcp', 'tcp6') and array[5].startswith('LISTEN') \
                        or proto in ('udp', 'udp6'):
                    port = (int(current_port), Protocol.from_value(proto))
                    listening_ports.add(port)
    except FileNotFoundError:
        # nothing to do
        pass

    return listening_ports


def get_checked_ports(_ports_to_monitor):
    """ Get a dict of pairs (listening port and protocol) and their listening
    state.

    :type _ports_to_monitor: set
    :param _ports_to_monitor: a set of ports to monitor
    :rtype: dict
    :return: a dict of pairs (listening port and protocol) and state
    """

    checked_ports = dict()

    if type(_ports_to_monitor) is set:
        listening_ports = get_listening_ports()
        ports_on_error = _ports_to_monitor - listening_ports
        ports_on_success = _ports_to_monitor - ports_on_error

        for p in ports_on_error:
            checked_ports[p] = False
        for p in ports_on_success:
            checked_ports[p] = True

    return checked_ports


def get_checked_services(_services_to_monitor):
    """ Get a dict of service names and their running state.

    :type _services_to_monitor: set
    :param _services_to_monitor: a set of services to monitor
    :rtype: dict
    :return: a dict of service names and state
    """

    results = dict()

    if type(_services_to_monitor) is set:
        for s in services_to_monitor:
            try:
                processes = check_output(['pgrep', '--exact', s],
                                         encoding='utf8').strip().split('\n')
                results[s] = len(processes) > 0
            except FileNotFoundError:
                results[s] = False
            except CalledProcessError:
                results[s] = False

    return results


def get_cpu_number():
    """ Get number of processors, or 'Unknown'.

    :rtype: int
    :return: the number of processors or 'Unknown'
    """

    try:
        with open('/proc/cpuinfo') as file_:
            cpuinfo = file_.read()
            return len(re.findall(r'\bprocessor\b', cpuinfo))
    except FileNotFoundError:
        return UNKNOWN


def add_memory_row(_rows, _warn_threshold, _crit_threshold, _format_str,
                   _title, _value, _percent):
    """ Add and format a memory row according to values and thresholds.

    :type _rows: list
    :param _rows: the rows as a list
    :type _warn_threshold: int
    :param _warn_threshold: the warning threshold
    :type _crit_threshold: int
    :param _crit_threshold: the critical threshold
    :type _format_str: str
    :param _format_str: the python format string with alignments
    :type _title: str
    :param _title: the row title
    :type _value: int
    :param _value: the value
    :type _percent: int
    :param _percent: the percent value
    :rtype: None
    :return: nothing
    """

    if type(_rows) is list:
        if _percent >= _crit_threshold:
            text_color = TermColor.red
        elif _percent >= _warn_threshold:
            text_color = TermColor.orange
        else:
            text_color = TermColor.green

        _rows.append(text_color + _format_str.format(_title, _value, _percent)
                     + TermColor.reset)


config = get_config(INI_FILE)

fs_exclude = config.get('fs_exclude', set())

ports_to_monitor = \
    {(p, Protocol.TCP) for p in config.get('tcp_ports_to_monitor', set())} \
    | {(p, Protocol.TCP6) for p in config.get('tcp6_ports_to_monitor', set())} \
    | {(p, Protocol.UDP) for p in config.get('udp_ports_to_monitor', set())} \
    | {(p, Protocol.UDP6) for p in config.get('udp6_ports_to_monitor', set())}

services_to_monitor = set(config.get('services_to_monitor', list()))

DISK_WARNING = config.get('disk_warning', 80) or 80
DISK_CRITICAL = config.get('disk_critical', 90) or 90
MEM_WARNING = config.get('mem_warning', 80) or 80
MEM_CRITICAL = config.get('mem_critical', 90) or 90
SWAP_WARNING = config.get('swap_warning', 10) or 10
SWAP_CRITICAL = config.get('swap_critical', 20) or 20

MAX_ROWS = config.get('max_rows', 15) or 15
col_width = config.get('col_width', 32) or 32
try:
    # shell mode
    term_size = os.get_terminal_size()
    COL_WIDTH = max(int((term_size.columns - 1 - 6) / 3), col_width)
except OSError:
    # cron mode
    COL_WIDTH = col_width

datetime = time.asctime()
hostname = get_hostname()
uptime = get_uptime()
iface = get_default_iface()
ip = get_ip(iface)
load = get_load()
processes = get_processes()
users = get_users()
mount_points = get_mount_points()
disk_space = get_disk_space(mount_points, fs_exclude)

meminfo = get_meminfo()

checked_ports = get_checked_ports(ports_to_monitor)
checked_services = get_checked_services(services_to_monitor)

columns = dict()
columns[0] = list()
columns[1] = list()
columns[2] = list()

disk_status_color = TermColor.green

for i in disk_space:
    if disk_space[i]['use%'] >= DISK_CRITICAL:
        disk_status_color = TermColor.red
    elif disk_space[i]['use%'] >= DISK_WARNING \
            and disk_status_color != TermColor.red:
        disk_status_color = TermColor.orange

columns[0].append(disk_status_color + TermColor.bold
                  + 'Disk status'.center(COL_WIDTH, '.') + TermColor.reset)

# noinspection PyStringFormat
columns[0].append(TermColor.bold
                  + f'{{:{COL_WIDTH - 10}}} free use%'.format('Partition')
                  + TermColor.reset)

if meminfo:
    mem_perc = int(100 - 100 * meminfo['MemFree'] / meminfo['MemTotal'])
    mem_used = int((meminfo['MemTotal'] - meminfo['MemFree']) / 1024)

    if meminfo['SwapTotal'] == 0:
        swap_perc = '---'
        swap_used = '---'
    else:
        swap_perc = int(100 - 100 * meminfo['SwapFree'] / meminfo['SwapTotal'])
        swap_used = int((meminfo['SwapTotal'] - meminfo['SwapFree']) / 1024)

    buffers = int(meminfo['Buffers'] / 1024)
    buffers_perc = int(100 * meminfo['Buffers'] / meminfo['MemTotal'])
    cached = int(meminfo['Cached'] / 1024)
    cached_perc = int(100 * meminfo['Cached'] / meminfo['MemTotal'])
    reclaimable = int(meminfo['SReclaimable'] / 1024)
    reclaimable_perc = int(100 * meminfo['SReclaimable'] / meminfo['MemTotal'])

    if mem_perc >= MEM_CRITICAL or swap_perc >= SWAP_CRITICAL \
            or buffers_perc >= MEM_CRITICAL or cached_perc >= MEM_CRITICAL:
        memory_status_color = TermColor.red + TermColor.bold
    elif mem_perc >= MEM_WARNING or swap_perc >= SWAP_WARNING \
            or buffers_perc >= MEM_WARNING or cached_perc >= MEM_WARNING:
        memory_status_color = TermColor.orange + TermColor.bold
    else:
        memory_status_color = TermColor.green + TermColor.bold

    mem_format = f'{{:<{COL_WIDTH - 12}}} {{:>6}} {{:>4}}'
    add_memory_row(columns[1], MEM_WARNING, MEM_CRITICAL, mem_format,
                   'Memory', mem_used, mem_perc)
    add_memory_row(columns[1], SWAP_WARNING, SWAP_CRITICAL, mem_format,
                   'Swap', swap_used, swap_perc)
    add_memory_row(columns[1], MEM_WARNING, MEM_CRITICAL, mem_format,
                   'Buffers', buffers, buffers_perc)
    add_memory_row(columns[1], MEM_WARNING, MEM_CRITICAL, mem_format,
                   'Cached', cached, cached_perc)
    add_memory_row(columns[1], MEM_WARNING, MEM_CRITICAL, mem_format,
                   'Reclaimable', reclaimable, reclaimable_perc)
else:
    memory_status_color = TermColor.green + TermColor.bold

# noinspection PyStringFormat
columns[1].insert(0, TermColor.bold
                  + f'{{:{COL_WIDTH - 8}}} MB    %'.format('Memory used')
                  + TermColor.reset)
columns[1].insert(0, memory_status_color
                  + 'Memory status'.center(COL_WIDTH, '.')
                  + TermColor.reset)

if all(checked_ports.values()) and all(checked_services.values()):
    services_ports_status_color = TermColor.green + TermColor.bold
else:
    services_ports_status_color = TermColor.red + TermColor.bold

columns[2].append(services_ports_status_color
                  + 'Services status'.center(COL_WIDTH, '.')
                  + TermColor.reset)

# noinspection PyStringFormat
columns[2].append(TermColor.bold
                  + f'{{:{COL_WIDTH - 7}}} status'.format('Services/ports')
                  + TermColor.reset)

for i in disk_space:
    if disk_space[i]['use%'] >= DISK_CRITICAL:
        partition_color = TermColor.red
    elif disk_space[i]['use%'] >= DISK_WARNING:
        partition_color = TermColor.orange
    else:
        partition_color = TermColor.green

    # noinspection PyStringFormat
    columns[0].append(partition_color
                      + f'{{:<{COL_WIDTH - 10}}} {{:>4}} {{:>4}}'
                      .format(i, disk_space[i]['available'],
                              disk_space[i]['use%']) + TermColor.reset)

for i in sorted(checked_services.keys()):
    if checked_services[i]:
        service_color = TermColor.green
        service_status = 'running'
    else:
        service_color = TermColor.red
        service_status = 'KO'

    # noinspection PyStringFormat
    columns[2].append(service_color + f'{{:<{COL_WIDTH - 9}}} {{:>8}}'
                      .format(i, service_status) + TermColor.reset)

for i in sorted(checked_ports.keys()):
    if checked_ports[i]:
        port_color = TermColor.green
        port_status = 'listening'
    else:
        port_color = TermColor.red
        port_status = 'KO'

    # noinspection PyStringFormat
    columns[2].append(port_color + f'{{:<{COL_WIDTH - 11}}} {{:>10}}'
                      .format(str(i[0]) + '/' + i[1].value, port_status)
                      + TermColor.reset)

print('\n' + TermColor.blue + TermColor.bold + 'System status for {} at {}'
      .format(hostname, datetime)
      .center(COL_WIDTH * 3 + 6, '.') + TermColor.reset)

print('\n\t\tIP: {}/{}'.format(ip,
                               iface if iface is not None else UNKNOWN))
print('\t\t{} user(s), {} processes'.format(len(users), processes))
print('\t\t{}'.format(uptime))
print('\t\tLoad: {} on {} CPU\n'.format(
    ' / '.join(['{} ({})'.format(load[k], k) for k in load.keys()]),
    get_cpu_number()))

column_sizes = [len(columns[x]) for x in columns]
rows_to_print = min(MAX_ROWS, max(*column_sizes))

for i in range(rows_to_print):
    row = ''
    for j in columns:
        if i < len(columns[j]):
            row += columns[j][i]
        else:
            row += ' ' * COL_WIDTH
        if j < len(columns) - 1:
            row += ' | '
    print(row)

print('\n' + TermColor.blue + TermColor.bold + 'pymotdstats {}'
      .format(VERSION)
      .rjust(COL_WIDTH * 3 + 6, '.') + TermColor.reset)