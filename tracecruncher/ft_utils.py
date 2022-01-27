"""
SPDX-License-Identifier: LGPL-2.1

Copyright 2019 VMware Inc, Yordan Karadzhov (VMware) <y.karadz@gmail.com>
"""

import sys
import time
import ctypes

from . import ftracepy as ft


def local_tep():
    """ Get the "tep" event of the current system (local).
    """
    tep = ft.tep_handle();
    tep.init_local(dir=ft.dir());

    return tep


def find_event_id(system, event):
    """ Get the unique identifier of a trace event.
    """
    tep = ft.tep_handle();
    tep.init_local(dir=ft.dir(), systems=[system]);

    return tep.get_event(system=system, name=event).id()


def short_kprobe_print(tep, events):
    """ Register short (no probe address) print for these kprobe events.
    """
    for e in events:
        if len(e.fields):
            tep.short_kprobe_print(id=e.evt_id, system=e.system, event=e.name)


class event:
    def __init__(self, system, name, static=True):
        """ Constructor.
        """
        self.system = system
        self.name = name
        self.instance_list = []
        if static:
            self.evt_id = find_event_id(system, name)
            if self.evt_id < 0:
                raise ValueError('Failed to find event {0}/{1}'.format(system, name))
        else:
            self.evt_id = -1

    def id(self):
        """ Retrieve the unique ID of the kprobe event.
        """
        return int(self.evt_id)

    def enable(self, instance=None):
        """ Enable this event.
        """
        if instance is None:
            ft.enable_event(system=self.system, event=self.name)
            self.instance_list.append('top')
        else:
            ft.enable_event(instance=instance, system=self.system, event=self.name)
            self.instance_list.append(instance)

        self.instance_list = list(set(self.instance_list))

    def disable(self, instance=None):
        """ Disable this event.
        """
        if instance is None:
            ft.disable_event(system=self.system, event=self.name)
            self.instance_list.remove('top')
        else:
            ft.disable_event(instance=instance,system=self.system, event=self.name)
            self.instance_list.remove(instance)

    def set_filter(self, filter, instance=None):
        """ Define a filter for this event.
        """
        if instance is None:
            ft.set_event_filter(system=self.system,
                                event=self.name,
                                filter=filter)
        else:
            ft.set_event_filter(instance=instance,
                                system=self.system,
                                event=self.name,
                                filter=filter)

    def clear_filter(self, instance=None):
        """ Define the filter for this event.
        """
        if instance is None:
            ft.clear_event_filter(system=self.system,
                                  event=self.name)
        else:
            ft.clear_event_filter(instance=instance,
                                  system=self.system,
                                  event=self.name)


class kprobe_base(event):
    def __init__(self, name, func=''):
        """ Constructor.
        """
        super().__init__(system=ft.tc_event_system(), name=name, static=False)
        self.func = func
        self.kp = None

    def set_function(self, name):
        """ Set the name of the function to be traced.
        """
        self.func = name


class kprobe(kprobe_base):
    def __init__(self, name, func=''):
        """ Constructor.
        """
        super().__init__(name, func)
        self.fields = {}

    def add_raw_field(self, name, probe):
        """ Add a raw definition of a data field to this probe.
        """
        self.fields[str(name)] = str(probe)

    def add_arg(self, name, param_id, param_type):
        """ Add a function parameter data field to this probe.
        """
        probe = '$arg{0}:{1}'.format(param_id, param_type)
        self.add_raw_field(name, probe)

    def add_ptr_arg(self, name, param_id, param_type, offset=0):
        """ Add a pointer function parameter data field to this probe.
        """
        probe = '+{0}($arg{1}):{2}'.format(offset, param_id, param_type)
        self.add_raw_field(name, probe)

    def add_array_arg(self, name, param_id, param_type, offset=0, size=-1):
        """ Add a array parameter data field to this probe.
        """
        if size < 0:
            size = 10

        ptr_size = ctypes.sizeof(ctypes.c_voidp)
        for i in range(size):
            field_name = name + str(i)
            probe = '+{0}(+{1}'.format(offset, i * ptr_size)
            probe += '($arg{0})):{1}'.format(param_id, param_type)
            self.add_raw_field(field_name, probe)

    def add_string_arg(self, name, param_id, offset=0, usr_space=False):
        """ Add a pointer function parameter data field to this probe.
        """
        p_type = 'ustring' if usr_space else 'string'
        self.add_ptr_arg(name=name,
                         param_id=param_id,
                         param_type=p_type,
                         offset=offset)

    def add_string_array_arg(self, name, param_id, offset=0, usr_space=False, size=-1):
        """ Add a string array parameter data field to this probe.
        """
        p_type = 'ustring' if usr_space else 'string'
        self.add_array_arg(name=name,
                           param_id=param_id,
                           param_type=p_type,
                           offset=offset,
                           size=size)

    def register(self):
        """ Register this probe to Ftrace.
        """
        probe = ' '.join('{!s}={!s}'.format(key,val) for (key, val) in self.fields.items())

        self.kp = ft.kprobe(event=self.name, function=self.func, probe=probe);
        self.evt_id = find_event_id(system=ft.tc_event_system(), event=self.name)


def parse_record_array_field(event, record, field, size=-1):
    """ Register this probe to Ftrace.
    """
    if size < 0:
        size = 10

    arr = []
    for i in range(size):
        field_name = field + str(i)
        val = event.parse_record_field(record=record, field=field_name)
        if (val == '(nil)'):
            break
        arr.append(val)

    return arr


class kretval_probe(kprobe_base):
    def __init__(self, name, func=''):
        """ Constructor.
        """
        super().__init__(name, func)

    def register(self):
        """ Register this probe to Ftrace.
        """
        self.kp = ft.kprobe(event=self.name, function=self.func);
        self.evt_id = find_event_id(system=ft.tc_event_system(), event=self.name)


class khist:
    def __init__(self, name, event, axes, weights=[],
                 sort_keys=[], sort_dir={}, find=False):
        """ Constructor.
        """
        self.name = name
        self.inst = None

        inst_name = name+'_inst'
        if find:
            self.inst = ft.find_instance(name=inst_name)
            self.attached = False
        else:
            self.inst = ft.create_instance(name=inst_name)
            self.attached = True

        self.hist = ft.hist(name=name,
                            system=event.system,
                            event=event.name,
                            axes=axes)

        for v in weights:
            self.hist.add_value(value=v)

        self.hist.sort_keys(keys=sort_keys)

        for key, val in sort_dir.items():
            self.hist.sort_key_direction(sort_key=key,
                                         direction=val)

        self.trigger = '{0}/events/{1}/{2}/trigger'.format(self.inst.dir(),
                                                           event.system,
                                                           event.name)

        if not find:
            # Put the kernel histogram on 'standby'
            self.hist.stop(self.inst)

    def __del__(self):
        """ Destructor.
        """
        if self.inst and self.attached:
            self.clear()

    def start(self):
        """ Start accumulating data.
        """
        self.hist.resume(self.inst)

    def stop(self):
        """ Stop accumulating data.
        """
        self.hist.stop(self.inst)

    def resume(self):
        """ Continue accumulating data.
        """
        self.hist.resume(self.inst)

    def data(self):
        """ Read the accumulated data.
        """
        return self.hist.read(self.inst)

    def clear(self):
        """ Clear the accumulated data.
        """
        self.hist.clear(self.inst)

    def detach(self):
        """ Detach the object from the Python module.
        """
        ft.detach(self.inst)
        self.attached = False

    def attach(self):
        """ Attach the object to the Python module.
        """
        ft.attach(self.inst)
        self.attached = True

    def is_attached(self):
        """ Check if the object is attached to the Python module.
        """
        return self.attached

    def __repr__(self):
        """ Read the descriptor of the histogram.
        """
        with open(self.trigger) as f:
            return f.read().rstrip()

    def __str__(self):
        return self.data()


def create_khist(name, event, axes, weights=[],
                 sort_keys=[], sort_dir={}):
    """ Create new kernel histogram.
    """
    try:
        hist = khist(name=name, event=event, axes=axes, weights=weights,
                     sort_keys=sort_keys, sort_dir=sort_dir, find=False)
    except Exception as err:
        msg = 'Failed to create histogram \'{0}\''.format(name)
        raise RuntimeError(msg) from err

    return hist


def find_khist(name, event, axes, instance=None,
               weights=[], sort_keys=[], sort_dir={}):
    """ Find existing kernel histogram.
    """
    try:
        hist = khist(name=name, event=event, axes=axes, weights=weights,
                     sort_keys=sort_keys, sort_dir=sort_dir, find=True)
    except Exception as err:
        msg = 'Failed to find histogram \'{0}\''.format(name)
        raise RuntimeError(msg) from err

    return hist
