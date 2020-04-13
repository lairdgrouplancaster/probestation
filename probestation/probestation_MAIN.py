"""
This example demonstrates how to make a graphical interface, and uses
a random number generator to simulate data so that it does not require
an instrument to use.
Run the program by changing to the directory containing this file and calling:
python gui.py
"""


'''------------------------------------------------------------------------------------------------
instrument addresses
------------------------------------------------------------------------------------------------'''
bias_source_meter_address = "USB0::0x05E6::0x2450::04305994::INSTR"
gate_source_address = "USB0::0x05E6::0x2450::04305994::INSTR"
'''---------------------------------------------------------------------------------------------'''


import sys
import os
from time import sleep
from datetime import datetime as dt
import pyqtgraph as pg
from queue import Queue
import threading

import random
import tempfile

import logging
log = logging.getLogger('')
log.addHandler(logging.NullHandler())

# pymeasure modules
from pymeasure.log import console_log
from pymeasure.experiment import Procedure, IntegerParameter, Parameter, FloatParameter
from pymeasure.experiment import Results
from pymeasure.display.Qt import QtGui
# modified pymeasure modules
from windows import ManagedWindow
from workers import QWorker, Worker
from measurements import TestProcedure, RandomFakePreTest



class MainWindow(ManagedWindow):

    def __init__(self, sourcemeter_address, gate_address):
        super(MainWindow, self).__init__(
            procedure_class_pretest=RandomFakePreTest,
            procedure_class=TestProcedure,
            inputs_list=[
                'wafername', 'savepath', 'chipcols', 'chiprows', 'devcols', 'devrows',
                'V_bias', 'V_bias_steps', 'I_bias_limit',
                'V_g_min', 'V_g_max', 'V_g_steps',
                'delay', 'NPLC_pretest', 'NPLC_gatesweep'
            ],
            displays=['devicename', 'seed'],
            x_axis='Gate Voltage (V)',
            y_axis='Current (A)'
        )
        self.setWindowTitle('probestation')
        
        self.pipeline = Queue(maxsize=10)       # queue to store tasks between producer and starter
        
        self.producer_done = threading.Event()  # thread safe flag: producer has finished creating all measurement tasks for current scan
        self.producer_done.set()
        self.starter_done = threading.Event()   # thread safe flag: starter has processed all measurement tasks for current scan
        self.starter_done.set()
        self.current_device_passed_pretest = threading.Event()  # thread safe flag: decides if measurement is run on device, is set by pretest measurement
        
        # instruments
        print("\nconnecting to instrument ", sourcemeter_address, " for bias")
        try:
            adapter_source = VISAAdapter(sourcemeter_address)
            self.sourcemeter = Keithley2450(adapter_source, max_stepsize = 10e-3, max_units_per_second = 100e-3)
        except:
            print("WARNING: no bias instruments\n")
        print("\nconnecting to instrument ", gate_address, " for gate")
        try:
            adapter_gate = VISAAdapter(gate_address)
            self.gate = Keithley2450(adapter_gate, max_stepsize = 1e-3, max_units_per_second = 20e-3)
        except:
            print("WARNING: no gate instruments\n")
        


    def queue_experiment(self, procedure):
        filename = os.path.join(procedure.datafolder, 'gatetrace.dat')

        results = Results(procedure, filename)
        experiment = self.new_experiment(results)

        self.manager.queue(experiment)
    
    
    def start_scan(self):
        '''
        Callback for GUI 'Start' button.
        Spawns two threads (one producer, one starter) for an automated scan of a sample.
        '''
        self.event_abort.clear()
        self._disable_inputs()
        self.updateProgressBars(0,0)
        
        self.producer_done.clear()
        self.prod_worker = QWorker('producer', self.producer, self.pipeline)
        self.prod_worker.setObjectName('PRODUCER')
        self.prod_worker.start()
        
        self.starter_done.clear()
        self.kickoff_worker = QWorker('starter', self.starter, self.pipeline)
        self.kickoff_worker.setObjectName('STARTER')
        self.kickoff_worker.signals.procedure.connect(self.queue_experiment)
        self.kickoff_worker.signals.progress.connect(self.updateProgressBars)
        self.kickoff_worker.signals.finished.connect(self._enable_inputs)
        self.kickoff_worker.start()
    
    
    def producer(self, queue):
        '''
        One of the two functions that are spawned in new threads once an automated scan of a
        wafer is triggered.
        Produces dictionaries of input parameters for the measurements that shall be performed on
        each sample on the wafer. Each dictionary contains parameters for one sample. Dictionaries
        are stored in the 'pipline' Queue.
        '''
        # read user input to parameters of tmp_instance of measurement Procedure
        tmpproc = self.make_procedure()
        curr_time = dt.now().strftime("%Y-%m-%d__%H-%M-%S")
        sample_string = curr_time+"__"+tmpproc.wafername
        folder = os.path.join(tmpproc.savepath, sample_string)
        os.makedirs(folder)
        
        # update movement vectors of StageStack
        self.stages.calc_coordinates_delta_hor(tmpproc.chipcols, tmpproc.devcols)
        self.stages.calc_coordinates_delta_vert(tmpproc.chiprows, tmpproc.devrows)
        
        # produce parameter sets for actual measurements
        for chipcol in range(tmpproc.chipcols):
            for chiprow in range(tmpproc.chiprows):
                for devcol in range(tmpproc.devcols):
                    for devrow in range(tmpproc.devrows):
                        #chipindex = str(chipcol)+str(chiprow)
                        #devicename = self.CHIPSTRINGLIST.get(chipindex)+str(10*devcol+devrow+11)
                        devicename = str(chipcol)+"_"+str(chiprow)+"_"+str(devcol)+"_"+str(devrow)
                        device_string = "dev_"+devicename
                        foldername = os.path.join(folder, device_string)
                        procdir = {
                            'wafername': tmpproc.wafername,
                            'savepath': tmpproc.savepath,
                            'devicename': devicename,
                            'datafolder': foldername,
                            'chipcols': chipcol,
                            'chiprows': chiprow,
                            'devcols': devcol,
                            'devrows': devrow,
                            'V_bias': tmpproc.V_bias,
                            'V_bias_steps': tmpproc.V_bias_steps,
                            'I_bias_limit' :tmpproc.I_bias_limit,
                            'V_g_min': tmpproc.V_g_min,
                            'V_g_max': tmpproc.V_g_max,
                            'V_g_steps': tmpproc.V_g_steps,
                            'delay': tmpproc.delay,
                            'seed': 1000*chipcol+100*chiprow+10*devcol+devrow,
                            'total_devices': [tmpproc.chiprows, tmpproc.chipcols*tmpproc.chiprows, tmpproc.devrows, tmpproc.devcols*tmpproc.devrows],
                        }
                        
                        queue.put(procdir)
                        
                        # producer handling of abort
                        if self.event_abort.is_set():
                            #print("PRODUCER abort")
                            del tmpproc
                            self.producer_done.set()
                            return False
        
        del tmpproc
        self.producer_done.set()
        return True
    
    
    def starter(self, queue):
        '''
        The second ot the two functions that are spawned in new threads once an automated scan of a
        wafer is triggered.
        Manages measurements and transitions between measurements. Picks up measurement tasks from
        the 'pipline' Queue.
        '''
        while (not self.producer_done.is_set() or not queue.empty()):
            procdir = queue.get()
            os.makedirs(procdir['datafolder'])
                
            print("\n\nmoving to device", procdir['devicename'])
            self.stages.stage_not_moving.clear()
            self.stage_signals.sig_stage_moveTo_command.emit(self.stages.calc_dev_coordinates(procdir['chipcols'], procdir['chiprows'], procdir['devcols'], procdir['devrows']))
            self.stages.stage_not_moving.wait()
            #print("done")
            sleep(1)
            #print("STARTER abort check 1")
            #print(self.event_abort.is_set())
            if self.event_abort.is_set():
                #print("STARTER abort after movement")
                break
                
            #print("STARTER pretest")
            procedure = self.procedure_class_pretest(parent_window=self)
            procedure.set_parameters(procdir, except_missing=False)
            datafile = os.path.join(procdir['datafolder'], 'pretest-IV.dat')
            results = Results(procedure, datafile)
            self.pretest_worker = Worker(results)
            self.pretest_worker.start()
            self.pretest_worker.join(timeout=3600)
            sleep(1)
            #print("STARTER abort check 2")
            if self.event_abort.is_set():
                #print("STARTER abort after pretest")
                break
                
            #print("STARTER gatesweep")
            if self.current_device_passed_pretest.isSet():
                #print("\t\t\t\t\t\t\t\tqueue measurement")
                procedure = self.procedure_class(parent_window=self)
                procedure.set_parameters(procdir, except_missing=False)
                self._has_no_measurement.clear()
                self.kickoff_worker.signals.procedure.emit(procedure)
                self._has_no_measurement.wait()
            
            progress_current_chip = (procdir['devcols']*procdir['total_devices'][2]+procdir['devrows']+1)/procdir['total_devices'][3]
            progress_total = (procdir['chipcols']*procdir['total_devices'][0]+procdir['chiprows']+progress_current_chip)/procdir['total_devices'][1]
            self.kickoff_worker.signals.progress.emit(int(progress_total*100) ,int(progress_current_chip*100))
            
            #print("STARTER abort check 3")
            #print(self.event_abort.is_set())
            if self.event_abort.is_set():
                #print("STARTER abort after gatesweep")
                break
        
        if not self.event_abort.is_set():
            self.stages.stage_not_moving.clear()
            self.stage_signals.sig_stage_moveTo_command.emit(self.stages._coordinates_center)
            self.stages.stage_not_moving.wait()
        #print("STARTER enable inputs")
        #self._enable_inputs()
        #print("STARTER set done flag")
        self.starter_done.set()
        return True



if __name__ == "__main__":
    app = QtGui.QApplication(sys.argv)
    window = MainWindow(bias_source_meter_address, gate_source_address)
    window.show()
    sys.exit(app.exec_())