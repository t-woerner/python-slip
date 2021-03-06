#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function

import sys
from gi.repository import GLib

import dbus
import dbus.service
import dbus.mainloop.glib

# FIND THE ACTUAL EXAMPLE CODE BELOW...

# try to find the module in the unpacked source tree

import os.path
import import_marker

# try to find the slip.dbus module

import imp

modfile = import_marker.__file__
path = os.path.dirname(modfile)
found = False
oldsyspath = sys.path
while not found and path and path != "/":
    path = os.path.abspath(os.path.join(path, os.path.pardir))
    try:
        slipmod = imp.find_module("slip", [path] + sys.path)
        if slipmod[1].startswith(path + "/"):
            found = True
            sys.path.insert(0, path)
            import slip.dbus.service
    except ImportError:
        pass

if not found:

    # fall back to system paths

    sys.path = oldsyspath
    import slip.dbus.service

# ...BELOW HERE:


class ExampleException(Exception):
    pass


class ExampleObject(slip.dbus.service.Object):

    def __init__(self, *p, **k):
        super(ExampleObject, self).__init__(*p, **k)
        self.config_data = """These are the contents of a configuration file.

They extend over some lines.

And one more."""
        print("service object constructed")

    def __del__(self):
        print("service object deleted")

    @slip.dbus.polkit.require_auth("org.fedoraproject.slip.example.read")
    @dbus.service.method("org.fedoraproject.slip.example.mechanism",
                         in_signature="", out_signature="s")
    def read(self):
        print("%s.read () -> '%s'" % (self, self.config_data))
        return self.config_data

    @slip.dbus.polkit.require_auth("org.fedoraproject.slip.example.write")
    @dbus.service.method("org.fedoraproject.slip.example.mechanism",
                         in_signature="s", out_signature="")
    def write(self, config_data):
        print("%s.write ('%s')" % (self, config_data))
        self.config_data = config_data

    @slip.dbus.polkit.require_auth("org.fedoraproject.slip.example.read")
    @dbus.service.method("org.fedoraproject.slip.example.mechanism",
                         in_signature="", out_signature="")
    def raise_exception(self):
        ex = ExampleException("Booh!")
        print(ex)
        raise ex


if __name__ == "__main__":
    debug_gc = "--debug-gc" in sys.argv[1:]

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SystemBus()

    name = dbus.service.BusName("org.fedoraproject.slip.example.mechanism",
                                bus)
    object = ExampleObject(name, "/org/fedoraproject/slip/example/object")

    mainloop = GLib.MainLoop()
    slip.dbus.service.set_mainloop(mainloop)

    if debug_gc:
        print("Debugging garbage collector.")
        from pprint import pformat
        import gc
        gc.enable()
        gc.set_debug(gc.DEBUG_LEAK)
        gc_timeout = 10

        def gc_collect_iter_no_generator():
            i = 0
            while True:
                yield i
                i += 1

        gc_collect_iter_no = gc_collect_iter_no_generator()

        def gc_collect():
            print("\n" + ">"*78 + "\n")
            print("#%d: garbage objects (%d):\n" % (next(gc_collect_iter_no),
                                                    len(gc.garbage)))
            for x in gc.garbage:
                print("%s\n  %s" % (type(x), pformat(x)))
            print("\n" + ">"*78 + "\n")
            return True
        id = GLib.timeout_add_seconds(gc_timeout, gc_collect)
        gc_collect()

    print("Running example service.")
    mainloop.run()
