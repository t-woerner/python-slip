# -*- coding: utf-8 -*-
# slip.dbus.service -- convenience functions for using dbus-activated
# services
#
# Copyright © 2008 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# Authors: Nils Philippsen <nphilipp@redhat.com>

"""This module contains convenience functions for using dbus-activated services."""

import dbus
import dbus.service

import gobject

__all__ = ['Object', 'InterfaceType', 'set_mainloop', 'polkit_auth_required']

__mainloop__ = None

def __glib_quit_cb__ ():
    global __mainloop__
    # assume a Glib mainloop
    __mainloop__.quit ()

__quit_cb__ = __glib_quit_cb__

def set_mainloop (mainloop):
    global __mainloop__
    __mainloop__ = mainloop

def set_quit_cb (quit_cb):
    global __quit_cb__
    __quit_cb__ = quit_cb

def quit_cb ():
    global __quit_cb__
    __quit_cb__ ()

SENDER_KEYWORD = "__slip_dbus_service_sender__"

class PolKit (object):
    @property
    def _systembus (self):
        if not hasattr (PolKit, "__systembus"):
            PolKit.__systembus = dbus.SystemBus ()
        return PolKit.__systembus

    @property
    def _dbusobj (self):
        if not hasattr (PolKit, "__dbusobj"):
            PolKit.__dbusobj = self._systembus.get_object ("org.freedesktop.PolicyKit", "/")
        return PolKit.__dbusobj

    class NotAuthorized (dbus.DBusException):
        _dbus_error_name = "org.fedoraproject.slip.dbus.service.PolKit.NotAuthorized"

    def IsSystemBusNameAuthorized (self, system_bus_name, action_id):
        revoke_if_one_shot = True
        return self._dbusobj.IsSystemBusNameAuthorized (action_id, system_bus_name, revoke_if_one_shot, dbus_interface = "org.freedesktop.PolicyKit")

    def IsProcessAuthorized (self, pid, action_id):
        revoke_if_one_shot = True
        return self._dbusobj.IsSystemBusNameAuthorized (action_id, pid, revoke_if_one_shot, dbus_interface = "org.freedesktop.PolicyKit")

polkit = PolKit ()

def wrap_method (method):
    global SENDER_KEYWORD

    #print "method.__dict__:", method.__dict__

    if method._dbus_sender_keyword != None:
        sender_keyword = method._dbus_sender_keyword
        hide_sender_keyword = False
    else:
        sender_keyword = SENDER_KEYWORD
        hide_sender_keyword = True

    def wrapped_method (self, *p, **k):
        self.sender_seen (k[sender_keyword])

        action_id = getattr (method, "_slip_polkit_auth_required", None)
        if not action_id:
            action_id = getattr (self, "default_polkit_auth_required", None)
        if action_id:
            authorized = polkit.IsSystemBusNameAuthorized (k[sender_keyword], action_id)
            if authorized != "yes":
                # leave 120 secs time to acquire authorization
                self.timeout_restart (duration = 120)
                raise PolKit.NotAuthorized (action_id = action_id, authorized = authorized)

        if hide_sender_keyword:
            del k[sender_keyword]

        retval = method (self, *p, **k)

        self.timeout_restart ()

        return retval

    for attr in filter (lambda x: x[:6] == "_dbus_", dir (method)):
        if attr == "_dbus_sender_keyword":
            wrapped_method._dbus_sender_keyword = sender_keyword
        else:
            setattr (wrapped_method, attr, getattr (method, attr))
        #delattr (method, attr)

    wrapped_method.func_name = method.func_name
    #print "wrapped_method.__dict__:", wrapped_method.__dict__

    return wrapped_method

class InterfaceType (dbus.service.InterfaceType):
    def __new__ (cls, name, bases, dct):
        for attrname, attr in dct.iteritems ():
            if getattr (attr, "_dbus_is_method", False):
                #print "method:", attr
                dct[attrname] = wrap_method (attr)
                #print "wrapped method:", dct[attrname]
        #print "dct:", dct
        return super (InterfaceType, cls).__new__ (cls, name, bases, dct)

def polkit_auth_required (polkit_auth):
    def polkit_auth_require (method):
        assert hasattr (method, "_dbus_is_method")

        setattr (method, "_slip_polkit_auth_required", polkit_auth)
        return method
    return polkit_auth_require

class Object (dbus.service.Object):
    __metaclass__ = InterfaceType

    # timeout & persistence
    persistent = False
    default_duration = 5
    duration = default_duration
    current_source = None
    quit_fn = None
    senders = set ()
    connections_senders = {}
    connections_smobjs = {}

    # PolicyKit
    default_polkit_auth_required = None

    @classmethod
    def _timeout_cb (cls):
        if len (Object.senders) == 0:
            quit_cb ()
            return False

        Object.current_source = None
        Object.duration = cls.default_duration

        return False

    def _name_owner_changed (self, name, old_owner, new_owner):
        conn = self.connection

        if not new_owner and (old_owner, conn) in Object.senders:
            Object.senders.remove ((old_owner, conn))
            Object.connections_senders[conn].remove (old_owner)

            if len (Object.connections_senders[conn]) == 0:
                Object.connections_smobjs[conn].remove ()
                del Object.connections_senders[conn]
                del Object.connections_smobjs[conn]

            if len (Object.senders) == 0 and Object.current_source == None:
                quit_cb ()

    def timeout_restart (self, duration = None):
        if not duration:
            duration = self.__class__.default_duration
        if not Object.duration or duration > Object.duration:
            Object.duration = duration
        if not Object.persistent or len (Object.senders) == 0:
            if Object.current_source:
                gobject.source_remove (Object.current_source)
            Object.current_source = gobject.timeout_add (Object.duration * 1000, self.__class__._timeout_cb)

    def sender_seen (self, sender):
        if (sender, self.connection) not in Object.senders:
            Object.senders.add ((sender, self.connection))
            if self.connection not in Object.connections_senders.keys ():
                Object.connections_senders[self.connection] = set ()
                Object.connections_smobjs[self.connection] = \
                        self.connection.add_signal_receiver (
                                handler_function = self._name_owner_changed,
                                signal_name = "NameOwnerChanged",
                                dbus_interface = "org.freedesktop.DBus")
            Object.connections_senders[self.connection].add (sender)
