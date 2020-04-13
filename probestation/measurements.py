# procedure classes for automated probestation
# to be used with pymeasure package

import os
import random
from time import sleep
import numpy as np

from pymeasure.experiment import Procedure, Results, IntegerParameter, Parameter, FloatParameter

import logging
log = logging.getLogger('')
log.addHandler(logging.NullHandler())




class PreTestIV(Procedure):
    # input parameters
    V_bias = FloatParameter('Bias Voltage maximum', units='mV', default=100)
    V_bias_steps = FloatParameter('Bias Voltage steps', units='mV', default=1)
    I_bias_limit = FloatParameter('Bias Current limit', units='uA', default=1)
    delay = FloatParameter('Delay Time', units='s', default=0.2)
    NPLC_pretest = IntegerParameter('Pretest NPLC', default=1)
        
    max_current = 0

    DATA_COLUMNS = ['Voltage (V)', 'Current (A)', 'Resistance (Ohm)']
    
    def __init__(self, parent_window=None):
        super().__init__()
        self.parent_window = parent_window
    
    def startup(self):
        print("\t\t\t\tstarting device pretest")
        log.info("Setting up instruments for PreTestIV")
        current_range = I_bias_limit*1e-6       # to uA from input
        for limit in (200, 20, 2, 0.2, 0.02):
            if limit > self.V_bias*1e-3:        # to mV from input
                source_limit = limit
            else:
                break
        self.parent_window.sourcemeter.apply_voltage(voltage_range=source_limit, compliance_current=current_range)
        self.parent_window.sourcemeter.measure_current(nplc=self.NPLC_pretest, current=current_range+0.05*current_range, auto_range=False)
        self.parent_window.sourcemeter.enable_source()
        
        sleep(1)
    
    def execute(self):
        V_bias_list = np.arange(0, self.V_bias+self.V_bias_steps, self.V_bias_steps)
        V_bias_list *= 1e-3                     # to mV from input
        steps = len(V_bias_list)
        
        log.info("Starting to ramp up the bias")
        for i, voltage in enumerate(V_bias_list):
            log.debug("Measuring current: %g mV" % voltage)

            #self.parent_window.sourcemeter.source_current = voltage
            self.parent_window.sourcemeter.ramp_to_voltage(voltage)
            sleep(self.delay)
            
            current = self.parent_window.sourcemeter.current
            if current > self.max_current:
                self.max_current = current

            if abs(voltage) <= 1e-10:
                resistance = np.nan
            else:
                resistance = voltage/current
            data = {
                'Voltage (V)': voltage,
                'Current (A)': current,
                'Resistance (Ohm)': resistance
            }
            self.emit('results', data)
            self.emit('progress', 100.*i/steps)
            if current > self.I_bias_limit:
                log.info("PreTest abort, current too high!")
                print("PreTest abort, current too high!")
                break
            if self.should_stop():
                log.warning("Catch stop command in procedure")
                break
    
    def shutdown(self):
        if self.max_current < 10e-9:
            self.parent_window.current_device_passed_pretest.clear()
            print("\t\t\t\t\t\t\t\t\t\tdevice failed")
            print("\t\t\t\t\t\t\t\t\t\tsafe sweep down")
            self.parent_window.sourcemeter.ramp_to_voltage(0)
            sleep(1)
            self.parent_window.sourcemeter.disable_source()
            print("\t\t\t\t\t\t\t\t\t\tPreTest shutdown finished")
        else:
            self.parent_window.current_device_passed_pretest.set()
            print("\t\t\t\t\t\t\t\tgood device")




class Gatesweep(Procedure):
    # input parameters
    wafername = Parameter('Wafer Name', default="Testchip")
    savepath = Parameter('Save path', default='D:\\probestation\\data')
    devicename = Parameter('Device', default="0000")
    datafolder = Parameter('Datafile path', default='D:\\probestation\\data\\dev_0000')
    chipcols = IntegerParameter('Chip columns', default=2)
    chiprows = IntegerParameter('Chip rows', default=4)
    devcols = IntegerParameter('Device columns', default=8)
    devrows = IntegerParameter('Device rows', default=8)
    V_bias = FloatParameter('Bias Voltage maximum', units='mV', default=100)
    V_bias_steps = FloatParameter('Bias Voltage steps', units='mV', default=1)
    I_bias_limit = FloatParameter('Bias Current limit', units='uA', default=1)
    V_g_min = FloatParameter('Gate Voltage minimum', units='V', default=-5)
    V_g_max = FloatParameter('Gate Voltage maximum', units='V', default=5)
    V_g_steps = IntegerParameter('Gate Voltage stepsize', units='mV', default=10)
    delay = FloatParameter('Delay Time', units='s', default=0.2)
    NPLC_pretest = IntegerParameter('Pretest NPLC', default=1)
    NPLC_gatesweep = IntegerParameter('Gatesweep NPLC', default=1)

    DATA_COLUMNS = ['Gate Voltage (V)', 'Current (A)']
    
    def __init__(self, parent_window=None):
        super().__init__()
        self.parent_window = parent_window

    def startup(self):
        log.info("Setting up instruments for Gatesweep")
        #self.parent_window.sourcemeter.apply_voltage(voltage_range=10, compliance_current=0.1)
        #self.parent_window.sourcemeter.measure_current(nplc=self.NPLC, current=1.05e-4, auto_range=False)
        if not self.parent_window.sourcemeter.source_enabled:
            self.parent_window.sourcemeter.enable_source()
        
        self.parent_window.gate.apply_voltage(voltage_range=20, compliance_current=1e-9)
        self.parent_window.gate.enable_source()
        
        sleep(1)

    def execute(self):
        V_gate_list_down = np.linspace(0, self.V_g_min, num = int(-self.V_g_min/(self.V_g_steps*2e-3)+1))
        V_gate_list_fullrange = np.linspace(self.V_g_min, self.V_g_max, num = int((self.V_g_max-self.V_g_min)/(self.V_g_steps*1e-3)+1))
        V_gate_list_return = np.linspace(self.V_g_max, 0, num = int(self.V_g_max/(self.V_g_steps*2e-3)+1))
        V_gate_list = np.concatenate((V_gate_list_down, V_gate_list_fullrange, V_gate_list_return)) # Include the reverse
        steps = len(V_gate_list)
        
        log.info("Ramping to bias voltage")
        self.parent_window.sourcemeter.ramp_to_voltage(self.V_bias)
        
        log.info("Starting to sweep the gate")
        for i, voltage in enumerate(V_gate_list):
            log.debug("Measuring current: %g mV" % voltage)

            #self.parent_window.sourcemeter.source_current = voltage
            self.parent_window.gate.ramp_to_voltage(voltage)
            sleep(self.delay)
            
            current = self.parent_window.sourcemeter.current
            
            data = {
                'Voltage (V)': voltage,
                'Current (A)': current
            }
            self.emit('results', data)
            self.emit('progress', 100.*i/steps)
            if current > self.I_bias_limit:
                log.info("Gatesweep abort, current too high!")
                print("gatesweep abort, current too high!")
                break
            if self.should_stop():
                log.warning("Catch stop command in procedure")
                break

    def shutdown(self):
        print("finished measurement, safe sweep down")
        self.parent_window.sourcemeter.ramp_to_voltage(0)
        self.parent_window.gate.ramp_to_voltage(0)
        self.parent_window.sourcemeter.disable_source()
        self.parent_window.gate.disable_source()
        print("Gatesweep shutdown finished")
        logmsg = "Finished device "+self.devicename+"\n"
        log.info(logmsg)




class RandomFakePreTest(Procedure):
    # input parameters
    V_bias = FloatParameter('Bias Voltage maximum', units='mV', default=100)
    V_bias_steps = FloatParameter('Bias Voltage steps', units='mV', default=10)
    I_bias_limit = FloatParameter('Bias Current limit', units='uA', default=1)
    delay = FloatParameter('Delay Time', units='s', default=0.1)
    NPLC_pretest = IntegerParameter('Pretest NPLC', default=1)
    seed = Parameter('Random Seed', default='12345')

    DATA_COLUMNS = ['Voltage (V)', 'Current (A)', 'Resistance (Ohm)']
    
    def __init__(self, parent_window=None):
        super().__init__()
        self.parent_window = parent_window
        self.max_current = 0
    
    def startup(self):
        log.info("Setting up random number generator")
        random.seed(self.seed)
    
    def execute(self):
        V_bias_list = np.arange(0, self.V_bias, self.V_bias_steps)
        V_bias_list *= 1e-3 # to mV from input
        steps = len(V_bias_list)
        
        print("running pretest")
        log.info("Starting to ramp up the bias")
        a = random.random()
        for i, voltage in enumerate(V_bias_list):
            log.debug("Measuring current: %g mV" % voltage)

            sleep(self.delay)
            
            current = 100*a*voltage
            if current > self.max_current:
                self.max_current = current

            if abs(voltage) <= 1e-10:
                resistance = np.nan
            else:
                resistance = voltage/current
            data = {
                'Voltage (V)': voltage,
                'Current (A)': current,
                'Resistance (Ohm)': resistance
            }
            self.emit('results', data)
            self.emit('progress', 100.*i/steps)
            if self.should_stop():
                log.warning("Catch stop command in procedure")
                break
        print("pretest current: ", self.max_current)
    
    def shutdown(self):
        if self.max_current < 50*self.V_bias*1e-3 or self.should_stop():
            self.parent_window.current_device_passed_pretest.clear()
            print("\t--> failed")
            #print("\t\t\t\t\t\t\t\t\t\tsafe sweep down")
            print("PreTest shutdown")
        else:
            self.parent_window.current_device_passed_pretest.set()
            print("\t--> passed")




class TestProcedure(Procedure):
    # input parameters
    wafername = Parameter('Wafer Name', default="Testchip")
    savepath = Parameter('Save path', default='D:\\probestation\\data')
    devicename = Parameter('Device', default="0000")
    datafolder = Parameter('Datafile path', default='D:\\probestation\\data\\dev_0000')
    chipcols = IntegerParameter('Chip columns', default=2)
    chiprows = IntegerParameter('Chip rows', default=4)
    devcols = IntegerParameter('Device columns', default=8)
    devrows = IntegerParameter('Device rows', default=8)
    V_bias = FloatParameter('Bias Voltage maximum', units='mV', default=100)
    V_bias_steps = FloatParameter('Bias Voltage steps', units='mV', default=10)
    I_bias_limit = FloatParameter('Bias Current limit', units='uA', default=1)
    V_g_min = FloatParameter('Gate Voltage minimum', units='V', default=-5)
    V_g_max = FloatParameter('Gate Voltage maximum', units='V', default=5)
    V_g_steps = IntegerParameter('Gate Voltage stepsize', units='mV', default=50)
    delay = FloatParameter('Delay Time', units='s', default=0.1)
    NPLC_pretest = IntegerParameter('Pretest NPLC', default=1)
    NPLC_gatesweep = IntegerParameter('Gatesweep NPLC', default=1)
    seed = Parameter('Random Seed', default='12345')

    DATA_COLUMNS = ['Gate Voltage (V)', 'Current (A)']
    
    def __init__(self, parent_window=None):
        super().__init__()
        self.parent_window = parent_window

    def startup(self):
        log.info("Setting up random number generator")
        random.seed(self.seed)

    def execute(self):
        V_gate_list_down = np.linspace(0, self.V_g_min, num = int(-self.V_g_min/(self.V_g_steps*2e-3)+1))
        V_gate_list_fullrange = np.linspace(self.V_g_min, self.V_g_max, num = int((self.V_g_max-self.V_g_min)/(self.V_g_steps*1e-3)+1))
        V_gate_list_return = np.linspace(self.V_g_max, 0, num = int(self.V_g_max/(self.V_g_steps*2e-3)+1))
        V_gate_list = np.concatenate((V_gate_list_down, V_gate_list_fullrange, V_gate_list_return)) # Include the reverse
        steps = len(V_gate_list)
        
        print("running measurement")
        log.info("Starting to generate numbers")
        a = random.random()
        b = random.random()
        c = random.random()
        self.V_g_steps = self.V_g_steps*5
        for i, voltage in enumerate(V_gate_list):
            current = 10*a*(voltage - b)**2 + 10*c + 5*random.random() + 1000*self.chipcols+100*self.chiprows+10*self.devcols+self.devrows
            data = {
                'Gate Voltage (V)': voltage,
                'Current (A)': current
            }
            log.debug("Produced numbers: %s" % data)
            self.emit('results', data)
            self.emit('progress', 100*i/steps)
            sleep(self.delay)
            if self.should_stop():
                log.warning("Catch stop command in procedure")
                break

    def shutdown(self):
        print("Finished device "+self.devicename+", safe sweep down")
        logmsg = "Finished device "+self.devicename
        log.info(logmsg)

