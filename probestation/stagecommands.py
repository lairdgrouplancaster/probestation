from ctypes import *
import os
import sys
import platform
from time import sleep
import re

from PyQt5.QtCore import QObject, pyqtSignal
from threading import Event

if sys.version_info >= (3,0):
    import urllib.parse

cur_dir = os.path.abspath(os.path.dirname(__file__))
if sys.version_info > (3,8):
    os.add_dll_directory(cur_dir)
os.environ["Path"] = cur_dir + ";" + os.environ["Path"]  # add dll

try: 
    from pyximc import *
except ImportError as err:
    print (
        """Can't import pyximc module. The most probable reason is that you changed the relative
        location of the testpython.py and pyximc.py files. See developers' documentation for details."""
    )
    exit()
'''except OSError as err:
    print (
        """Can't load libximc library. Please add all shared libraries to the appropriate places.
        It is decribed in detail in developers' documentation. On Linux make sure you installed
        libximc-dev package.\nMake sure that the architecture of the system and the interpreter
        is the same"""
    )
    exit()'''

# variable 'lib' points to a loaded library
# note that ximc uses stdcall on win
print("Stage controller library loaded")

sbuf = create_string_buffer(64)
lib.ximc_version(sbuf)
print("Library version: " + sbuf.raw.decode().rstrip("\0") + "\n")





class StageStack(QObject):
    def __init__(self):
        super(StageStack, self).__init__()
        
        print("Initialising motorised stage stack")
        # PyQt Signals
        finished = pyqtSignal()
        
        # Events
        self.stage_not_moving = Event()
        self.stage_not_moving.set()
        self.stage_emergency_stop_call = Event()
        self.stage_emergency_stop_call.clear()
        
        # Device search and enumeration with probing. It gives more information about devices.
        self.probe_flags = EnumerateFlags.ENUMERATE_PROBE
        self.enum_hints = b"addr=" # Use this hint string for broadcast enumerate
        self.devenum = lib.enumerate_devices(self.probe_flags, self.enum_hints)

        dev_count = lib.get_device_count(self.devenum)
        print("Found " + repr(dev_count) + " stage motors")
        
        print("Assigning motors to movement axes")
        self.stage_x, self.stage_y, self.stage_z = None, None, None
        self.controller_name = controller_name_t()
        for dev_ind in range(0, dev_count):
            dev_name = lib.get_device_name(self.devenum, dev_ind)
            if type(dev_name) is str:
                dev_name = dev_name.encode()
            result = lib.get_enumerate_device_controller_name(self.devenum, dev_ind, byref(self.controller_name))
            if result == Result.Ok:
                stage = lib.open_device(dev_name)
                serial = c_uint()
                result = lib.get_serial_number(stage, byref(serial))
                if result == Result.Ok:
                    if serial.value == 18162:
                        self.stage_x = stage
                    elif serial.value == 18212:
                        self.stage_y = stage
                    elif serial.value == 18232:
                        self.stage_z = stage
                    else:
                        print("Found a motor that can't be identified")
        
        if self.stage_x is None or self.stage_y is None or self.stage_z is None:
            self.motorsOk = False
            print("WARNING: couldn't assign all stage motors!\n")
        else:
            self.motorsOk = True
            print("Motors connected\n")
        
        
        for stage in (self.stage_x, self.stage_y):
            self.change_speed(stage, 500)
        self.change_speed(self.stage_z, 2000)
        """
        TODO:
        
        initialise stage parameters like acceleration, microstep mode
        check, if speed values are ok
        """
        
        # bit flags for up/down/fast_movemnet/north/east/south/west
        self._movement_flag = 0b0000000
        
        # stored coordinates
        self._coordinates_center = [[0,0],[0,0],[500,0]]
        self._coordinates_load = [[0,0],[-14500,0],[500,0]]
        self._coordinates_dev_00 = [[-8000,0],[-10000,0],[5000,0]]
        self._coordinates_dev_i0 = [[8000,0],[-11000,0],[4500,0]]
        self._coordinates_dev_0j = [[-7500,0],[10000,0],[5500,0]]
        self._coordinates_delta_hor = [[0,0],[0,0],[500,0]]
        self._coordinates_delta_vert = [[0,0],[0,0],[500,0]]
        self._automovement_safe_height = 500
    
    
    
    def startup_feedback(self):
        print("stage thread setup finished\n")
    
    
    
    def move(self, direction):
        self.stage_not_moving.clear()
        if direction == "north":
            self._movement_flag += 0b0001000
            if self.motorsOk:
                lib.command_right(self.stage_y)
        elif direction == "east":
            self._movement_flag += 0b0000100
            if self.motorsOk:
                lib.command_right(self.stage_x)
        elif direction == "south":
            self._movement_flag += 0b0000010
            if self.motorsOk:
                lib.command_left(self.stage_y)
        elif direction == "west":
            self._movement_flag += 0b0000001
            if self.motorsOk:
                lib.command_left(self.stage_x)
        elif direction == "up":
            self._movement_flag += 0b1000000
            if self.motorsOk:
                lib.command_right(self.stage_z)
        elif direction == "down":
            self._movement_flag += 0b0100000
            if self.motorsOk:
                lib.command_left(self.stage_z)
        else:
            print("unknown stage movement command")
        if not self.motorsOk:
            print("move ", direction)
    
    
    def stop(self, direction):
        self.stage_not_moving.set()
        if direction == "north":
            self._movement_flag -= 0b0001000
            if self.motorsOk:
                lib.command_sstp(self.stage_y)
                lib.command_wait_for_stop(self.stage_y, 20)
        elif direction == "east":
            self._movement_flag -= 0b0000100
            if self.motorsOk:
                lib.command_sstp(self.stage_x)
                lib.command_wait_for_stop(self.stage_x, 20)
        elif direction == "south":
            self._movement_flag -= 0b0000010
            if self.motorsOk:
                lib.command_sstp(self.stage_y)
                lib.command_wait_for_stop(self.stage_y, 20)
        elif direction == "west":
            self._movement_flag -= 0b0000001
            if self.motorsOk:
                lib.command_sstp(self.stage_x)
                lib.command_wait_for_stop(self.stage_x, 20)
        elif direction == "up":
            self._movement_flag -= 0b1000000
            if self.motorsOk:
                lib.command_sstp(self.stage_z)
                lib.command_wait_for_stop(self.stage_z, 20)
        elif direction == "down":
            self._movement_flag -= 0b0100000
            if self.motorsOk:
                lib.command_sstp(self.stage_z)
                lib.command_wait_for_stop(self.stage_z, 20)
        else:
            print("unknown stage movement command")
        if not self.motorsOk:
            print("stop ", direction)
    
    
    def stage_movement_emergency_stop(self):
        print("stage emergency stop")
        self.stage_not_moving.set()
        self._movement_flag = 0b0000000
        if self.motorsOk:
            for stage in (self.stage_x, self.stage_y, self.stage_z):
                lib.command_sstp(stage)
            for stage in (self.stage_x, self.stage_y, self.stage_z):
                lib.command_wait_for_stop(stage, 10)
        self.stage_emergency_stop_call.clear()
    
    
    def initialise_speed_change(self, switch):
        #print("speed change ", switch)
        if switch > 0:
            self.speed_up()
        else:
            self.slow_down()
    
    
    def change_speed(self, stage, new_speed):
        mvst = move_settings_t()
        lib.get_move_settings(stage, byref(mvst))
        # Change current speed
        mvst.Speed = int(new_speed)
        # Write new move settings to controller
        lib.set_move_settings(stage, byref(mvst))
    
    
    def speed_up(self):
        self._movement_flag += 0b0010000
        if self.motorsOk:
            for stage in (self.stage_x, self.stage_y):
                self.change_speed(stage, 2000)
            self.change_speed(self.stage_z, 4500)
        else:
            print("speed up")
    
    
    def slow_down(self):
        self._movement_flag -= 0b0010000
        if self.motorsOk:
            for stage in (self.stage_x, self.stage_y, self.stage_z):
                self.change_speed(stage, 500)
            self.change_speed(self.stage_z, 2000)
        else:
            print("slow down")
    
    
    def read_stage_position(self, stage):
        if self.motorsOk:
            x_pos = get_position_t()
            lib.get_position(stage, byref(x_pos))
            return [x_pos.Position, x_pos.uPosition]
        else:
            return [1000, 0]
    
    
    def capture_coords(self, device, calling_window):
        n = 0
        if device == "00":
            if self.motorsOk:
                for stage in (self.stage_x, self.stage_y, self.stage_z):
                    self._coordinates_dev_00[n] = self.read_stage_position(stage)
                    n += 1
            
            calling_window.button_capture_00.setText("dev_00 OK")
            calling_window.button_goto_00.setEnabled(True)
            if calling_window.button_goto_i0.isEnabled() and calling_window.button_goto_0j.isEnabled():
                calling_window.button_start.setEnabled(True)
            
        elif device == "i0":
            if self.motorsOk:
                for stage in (self.stage_x, self.stage_y, self.stage_z):
                    self._coordinates_dev_i0[n] = self.read_stage_position(stage)
                    n += 1
            
            calling_window.button_capture_i0.setText("dev_i0 OK")
            calling_window.button_goto_i0.setEnabled(True)
            if calling_window.button_goto_00.isEnabled() and calling_window.button_goto_0j.isEnabled():
                calling_window.button_start.setEnabled(True)
            
        elif device == "0j":
            if self.motorsOk:
                for stage in (self.stage_x, self.stage_y, self.stage_z):
                    self._coordinates_dev_0j[n] = self.read_stage_position(stage)
                    n += 1
            
            calling_window.button_capture_0j.setText("dev_0j OK")
            calling_window.button_goto_0j.setEnabled(True)
            if calling_window.button_goto_i0.isEnabled() and calling_window.button_goto_00.isEnabled():
                calling_window.button_start.setEnabled(True)
            
        else:
            print("tried to capture coords that I don't need anyways")
        
        self._calc_new_safe_height()
    
    
    def goto_coords(self, coords):
        print("moving to corrds ", coords)
        self.stage_not_moving.clear()
        self.speed_up()
        if self.motorsOk:
            # move to a safe height
            lib.command_move(self.stage_z, self._automovement_safe_height, 0)
            self._interruptable_wait_for_stop(self.stage_z, 20)
            if self.stage_emergency_stop_call.isSet():
                self.slow_down()
                return False
            # horizontal movement to final position
            lib.command_move(self.stage_x, coords[0][0], coords[0][1])
            lib.command_move(self.stage_y, coords[1][0], coords[1][1])
            self._interruptable_wait_for_stop(self.stage_y, 20)
            self._interruptable_wait_for_stop(self.stage_x, 20)
            if self.stage_emergency_stop_call.isSet():
                self.slow_down()
                return False
            # vertical movement to final position
            lib.command_move(self.stage_z, coords[2][0], coords[2][1])
            self._interruptable_wait_for_stop(self.stage_z, 20)
            if self.stage_emergency_stop_call.isSet():
                self.slow_down()
                return False
        else:
            sleep(2)
        self.slow_down()
        sleep(1)
        self.stage_not_moving.set()
    
    
    def coordinates_cleanup(self, coords):            # supports only 1/256 microstep mode. modify for different microstep modes?
        for n in range(3):
            coords[n][0] = int(coords[n][0])
            coords[n][1] = int(coords[n][1])
            while coords[n][1] > 255:
                coords[n][0] += 1
                coords[n][1] -= 256
            while coords[n][1] < -255:
                coords[n][0] -= 1
                coords[n][1] += 256
            if coords[n][0] < 0 and coords[n][1] > 0:
                coords[n][0] +=1
                coords[n][1] = -256 + coords[n][1]
            if coords[n][0] > 0 and coords[n][1] < 0:
                coords[n][0] -= 1
                coords[n][1] = 256 - coords[n][1]
        return coords
    
    
    def coords_boudary_check(self, coords):
        if abs(coords[0][0]) > 14600 or abs(coords[1][0]) > 14600 or coords[2][0] < 0 or coords[2][0] > 156000:
            #print(coords)
            raise Exception("Stage coordinates out of bounds")
    
    
    def calc_coordinates_delta_hor(self, chipcols, devcols):
        tmp = [[0,0],[0,0],[0,0]]
        if chipcols > 1 or devcols > 1:
            for n in range(3):
                tmp[n][0] = ( self._coordinates_dev_i0[n][0] - self._coordinates_dev_00[n][0] ) / ( 10 * (chipcols-1) + (devcols-1) )
                tmp[n][1] = ( self._coordinates_dev_i0[n][1] - self._coordinates_dev_00[n][1] ) / ( 10 * (chipcols-1) + (devcols-1) )
        self._coordinates_delta_hor = self.coordinates_cleanup(tmp)
    
    
    def calc_coordinates_delta_vert(self, chiprows, devrows):
        tmp = [[0,0],[0,0],[0,0]]
        if chiprows > 1 or devrows > 1:
            for n in range(3):
                tmp[n][0] = ( self._coordinates_dev_0j[n][0] - self._coordinates_dev_00[n][0] ) / ( 10 * (chiprows-1) + (devrows-1) )
                tmp[n][1] = ( self._coordinates_dev_0j[n][1] - self._coordinates_dev_00[n][1] ) / ( 10 * (chiprows-1) + (devrows-1) )
        self._coordinates_delta_vert = self.coordinates_cleanup(tmp)
    
    
    def calc_dev_coordinates(self, chipcol, chiprow, devcol, devrow):
        tmp = [[0,0],[0,0],[0,0]]
        for n in range(3):
            tmp[n][0] = self._coordinates_dev_00[n][0] + (10*chipcol+devcol)*self._coordinates_delta_hor[n][0] + (10*chiprow+devrow)*self._coordinates_delta_vert[n][0]
            tmp[n][1] = self._coordinates_dev_00[n][1] + (10*chipcol+devcol)*self._coordinates_delta_hor[n][1] + (10*chiprow+devrow)*self._coordinates_delta_vert[n][1]
        tmp = self.coordinates_cleanup(tmp)
        self.coords_boudary_check(tmp)
        return tmp
    
    
    def _calc_new_safe_height(self):
        self._automovement_safe_height = min(self._coordinates_dev_00[2][0],self._coordinates_dev_i0[2][0],self._coordinates_dev_0j[2][0])
        self._automovement_safe_height -= 20000
        if self._automovement_safe_height < 500:
            self._automovement_safe_height = 500
    
    
    def _interruptable_wait_for_stop(self, stage, delay):
        sleep(0.3)
        stage_status = status_t()
        lib.get_status(stage, byref(stage_status))
        while abs(stage_status.CurSpeed) > 0 and not self.stage_emergency_stop_call.isSet():
            lib.get_status(stage, byref(stage_status))
            sleep(delay*1e-3)


