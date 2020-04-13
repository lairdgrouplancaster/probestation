# Modified version of the pymeasure.windows module.
# The main window of the probestation GUI is built on top of this.

from datetime import datetime as dt
from time import sleep

import logging

import pyqtgraph as pg

import threading

# pymeasure modules
from pymeasure.display.browser import BrowserItem
from pymeasure.display.curves import ResultsCurve
#from pymeasure.display.manager import Manager, Experiment
from pymeasure.display.Qt import QtCore, QtGui
from pymeasure.experiment.results import Results
# modified pymeasure modules
from widgets import PlotWidget, BrowserWidget, InputsWidget, LogWidget, ResultsDialog
from manager import Manager, Experiment

# PyQt5 threading elements
from PyQt5.QtCore import QObject, QThread, pyqtSignal

# custom class for motorized stage control
from stagecommands import *


log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


class PlotterWindow(QtGui.QMainWindow):
    """
    A window for plotting experiment results. Should not be
    instantiated directly, but only via the
    :class:`~pymeasure.display.plotter.Plotter` class.

    .. seealso::

        Tutorial :ref:`tutorial-plotterwindow`
            A tutorial and example code for using the Plotter and PlotterWindow.

    .. attribute plot::

        The `pyqtgraph.PlotItem`_ object for this window. Can be
        accessed to further customise the plot view programmatically, e.g.,
        display log-log or semi-log axes by default, change axis range, etc.

    .. pyqtgraph.PlotItem: http://www.pyqtgraph.org/documentation/graphicsItems/plotitem.html

    """
    def __init__(self, plotter, refresh_time=0.1, parent=None):
        super().__init__(parent)
        self.plotter = plotter
        self.refresh_time = refresh_time
        columns = plotter.results.procedure.DATA_COLUMNS

        self.setWindowTitle('Results Plotter')
        self.main = QtGui.QWidget(self)

        vbox = QtGui.QVBoxLayout(self.main)
        vbox.setSpacing(0)

        hbox = QtGui.QHBoxLayout()
        hbox.setSpacing(6)
        hbox.setContentsMargins(-1, 6, -1, -1)

        file_label = QtGui.QLabel(self.main)
        file_label.setText('Data Filename:')

        self.file = QtGui.QLineEdit(self.main)
        self.file.setText(plotter.results.data_filename)

        hbox.addWidget(file_label)
        hbox.addWidget(self.file)
        vbox.addLayout(hbox)

        self.plot_widget = PlotWidget(columns, refresh_time=self.refresh_time, check_status=False)
        self.plot = self.plot_widget.plot

        vbox.addWidget(self.plot_widget)

        self.main.setLayout(vbox)
        self.setCentralWidget(self.main)
        self.main.show()
        self.resize(800, 600)

        self.curve = ResultsCurve(plotter.results, columns[0], columns[1],
                                  pen=pg.mkPen(color=pg.intColor(0), width=2), antialias=False)
        self.plot.addItem(self.curve)

        self.plot_widget.updated.connect(self.check_stop)

    def quit(self, evt=None):
        log.info("Quitting the Plotter")
        self.close()
        self.plotter.stop()

    def check_stop(self):
        """ Checks if the Plotter should stop and exits the Qt main loop if so
        """
        if self.plotter.should_stop():
            QtCore.QCoreApplication.instance().quit()



class WindowStageSignals(QObject):
    sig_stage_move_command = pyqtSignal(str)
    sig_stage_stop_command = pyqtSignal(str)
    sig_stage_speed_change = pyqtSignal(int)
    sig_stage_emergency_stop = pyqtSignal()
    sig_stage_capture_command = pyqtSignal(str, object)
    sig_stage_moveTo_command = pyqtSignal(object)


class ManagedWindow(QtGui.QMainWindow):
    """
    Abstract base class.

    The ManagedWindow provides an interface for inputting experiment
    parameters, running several experiments
    (:class:`~pymeasure.experiment.procedure.Procedure`), plotting
    result curves, and listing the experiments conducted during a session.

    The ManagedWindow uses a Manager to control Workers in a Queue,
    and provides a simple interface. The :meth:`~.queue` method must be
    overridden by the child class.

    .. seealso::

        Tutorial :ref:`tutorial-managedwindow`
            A tutorial and example on the basic configuration and usage of ManagedWindow.

    .. attribute:: plot

        The `pyqtgraph.PlotItem`_ object for this window. Can be
        accessed to further customise the plot view programmatically, e.g.,
        display log-log or semi-log axes by default, change axis range, etc.

    .. _pyqtgraph.PlotItem: http://www.pyqtgraph.org/documentation/graphicsItems/plotitem.html


    """
    EDITOR = 'gedit'

    def __init__(self, procedure_class_pretest, procedure_class, inputs_list=(), displays=(), x_axis=None, y_axis=None,
                 log_channel='', log_level=logging.INFO, parent=None):
        print("Building main window\n")
        super().__init__(parent)
        app = QtCore.QCoreApplication.instance()
        app.aboutToQuit.connect(self.quit)
        
        # logging
        self.log = logging.getLogger(log_channel)
        self.log_level = log_level
        log.setLevel(log_level)
        self.log.setLevel(log_level)
        
        # procedures/measurements and plotting
        self.procedure_class_pretest = procedure_class_pretest
        self.procedure_class = procedure_class
        self.inputs_list = inputs_list
        self.displays = displays
        self.x_axis, self.y_axis = x_axis, y_axis
        
        # GUI
        self._create_widgets()
        self._connect_widgets()
        self._layout_widgets()
        self.frame_input_stages.installEventFilter(self)
        for button in self.BUTTONS:
            button.installEventFilter(self)
        
        self.setup_plot(self.plot)
        
        # stages
        self.stage_thread = QThread()
        self.stages = StageStack()
        self.stages.moveToThread(self.stage_thread)
        self.stage_thread.started.connect(self.stages.startup_feedback)
        self.stage_thread.start()
        # stage signals
        self.stage_signals = WindowStageSignals()
        self.stage_signals.sig_stage_move_command.connect(self.stages.move)
        self.stage_signals.sig_stage_stop_command.connect(self.stages.stop)
        self.stage_signals.sig_stage_speed_change.connect(self.stages.initialise_speed_change)
        self.stage_signals.sig_stage_emergency_stop.connect(self.stages.stage_movement_emergency_stop)
        self.stage_signals.sig_stage_capture_command.connect(self.stages.capture_coords)
        self.stage_signals.sig_stage_moveTo_command.connect(self.stages.goto_coords)
        
        # flags
        self._has_no_measurement = threading.Event()
        self._has_no_measurement.set()
        self.event_abort = threading.Event()    # thread safe flag: abort automated scan
        self.event_abort.clear()
    
    
    def _create_widgets(self):
        '''
        Creates all widgets for the ManagedWindow
        '''
        # buttons
        self.BUTTONS = []
        #       coordinate capture buttons
        self.button_capture_00 = QtGui.QPushButton("dev_00")
        self.button_capture_i0 = QtGui.QPushButton("dev_i0")
        self.button_capture_0j = QtGui.QPushButton("dev_0j")
        self.BUTTONS.extend([self.button_capture_00, self.button_capture_i0, self.button_capture_0j])
        #       go to captured coordinates buttons
        self.button_goto_center = QtGui.QPushButton("center")
        self.button_goto_load = QtGui.QPushButton("load")
        self.button_goto_00 = QtGui.QPushButton("dev_00")
        self.button_goto_00.setEnabled(False)
        self.button_goto_i0 = QtGui.QPushButton("dev_i0")
        self.button_goto_i0.setEnabled(False)
        self.button_goto_0j = QtGui.QPushButton("dev_0j")
        self.button_goto_0j.setEnabled(False)
        self.BUTTONS.extend([self.button_goto_center, self.button_goto_load, self.button_goto_00, self.button_goto_i0, self.button_goto_0j])
        #       automated scan kickoff and abort
        self.button_start = QtGui.QPushButton("Start Scan")
        self.button_start.setEnabled(False)
        self.button_abort = QtGui.QPushButton("Abort current")
        self.button_abort.setEnabled(False)
        self.button_abort_all = QtGui.QPushButton("Abort all")
        self.button_abort_all.setEnabled(False)
        self.BUTTONS.extend([self.button_start, self.button_abort, self.button_abort_all])
        
        # input lines
        self.widget_inputlines = InputsWidget(
            self.procedure_class,
            self.inputs_list,
            parent=self
        )
        
        # output screens (plot, log, browser)
        #       plot
        self.widget_plot = PlotWidget(self.procedure_class.DATA_COLUMNS, self.x_axis, self.y_axis)
        self.plot = self.widget_plot.plot
        #       log
        self.widget_log = LogWidget()
        self.log.addHandler(self.widget_log.handler)  # needs to be in Qt context?
        log.info("ManagedWindow connected to logging")
        #       browser
        self.widget_browser = BrowserWidget(
            self.procedure_class,
            self.displays,
            [self.x_axis, self.y_axis],
            parent=self
        )
        self.browser = self.widget_browser.browser
        self.browser.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        #       autoscan progressbars
        self.progressbar_chip = QtGui.QProgressBar()
        self.progressbar_chip.setRange(0, 100)
        self.progressbar_chip.setValue(0)
        self.progressbar_wafer = QtGui.QProgressBar()
        self.progressbar_wafer.setRange(0, 100)
        self.progressbar_wafer.setValue(0)
        
        # background stuff (manager)
        self.manager = Manager(self.plot, self.browser, log_level=self.log_level, parent=self)
    
    
    def _connect_widgets(self):
        '''
        Connect all widget signals to corresponding slots in the window
        '''
        # buttons
        #       coordinate capture buttons
        self.button_capture_00.clicked.connect(lambda : self.stage_signals.sig_stage_capture_command.emit("00", self))
        self.button_capture_i0.clicked.connect(lambda : self.stage_signals.sig_stage_capture_command.emit("i0", self))
        self.button_capture_0j.clicked.connect(lambda : self.stage_signals.sig_stage_capture_command.emit("0j", self))
        #       go to captured coordinates buttons
        self.button_goto_center.clicked.connect(lambda  : self.stage_signals.sig_stage_moveTo_command.emit(self.stages._coordinates_center))
        self.button_goto_load.clicked.connect(lambda  : self.stage_signals.sig_stage_moveTo_command.emit(self.stages._coordinates_load))
        self.button_goto_00.clicked.connect(lambda  : self.stage_signals.sig_stage_moveTo_command.emit(self.stages._coordinates_dev_00))
        self.button_goto_i0.clicked.connect(lambda : self.stage_signals.sig_stage_moveTo_command.emit(self.stages._coordinates_dev_i0))
        self.button_goto_0j.clicked.connect(lambda : self.stage_signals.sig_stage_moveTo_command.emit(self.stages._coordinates_dev_0j))
        #       automated scan kickoff and abort
        self.button_start.clicked.connect(self.start_scan)
        self.button_abort.clicked.connect(self.abort)
        self.button_abort_all.clicked.connect(self.abort_all)
        #       browser buttons
        self.widget_browser.show_button.clicked.connect(self.show_experiments)
        self.widget_browser.hide_button.clicked.connect(self.hide_experiments)
        self.widget_browser.clear_button.clicked.connect(self.clear_experiments)
        
        # browser events
        self.browser.customContextMenuRequested.connect(self.browser_item_menu)
        self.browser.itemChanged.connect(self.browser_item_changed)
        
        # manager signals
        self.manager.queued.connect(self.queued)
        self.manager.running.connect(self.running)
        self.manager.finished.connect(self.experiment_finished)
        #self.manager.aborted.connect(self.experiment_finished)
        self.manager.abort_returned.connect(self.resume)
        self.manager.log.connect(self.log.handle)
    
    
    def _layout_widgets(self):
        '''
        Organise the layout of the window. Uses tab widgets (QTabWidget and a custom childclass thereof),
        QWidgets as frames, 
        '''
        # main frame
        main = QtGui.QWidget()
        # sub frames
        frame_input_sample = QtGui.QWidget()
        self.frame_input_stages = QtGui.QWidget(self)
        
        # layout groups
        #       tab layouts
        layout_v_input_sample = QtGui.QVBoxLayout()
        layout_v_input_stages = QtGui.QVBoxLayout()
        #       horizontal button groups
        layout_h_capture_buttons = QtGui.QHBoxLayout()
        layout_h_goto_buttons = QtGui.QHBoxLayout()
        layout_h_goto_buttons2 = QtGui.QHBoxLayout()
        layout_h_automation_buttons = QtGui.QHBoxLayout()
        #       main frame columns
        layout_h_main_columns = QtGui.QHBoxLayout()
        
        # split main right column into top/bottom
        main_right_col = QtGui.QSplitter(QtCore.Qt.Vertical)
        
        
        # fill button layouts
        layout_h_capture_buttons.setSpacing(10)
        layout_h_capture_buttons.setContentsMargins(-1, 6, -1, 6)
        layout_h_capture_buttons.addWidget(self.button_capture_00)
        layout_h_capture_buttons.addWidget(self.button_capture_i0)
        layout_h_capture_buttons.addWidget(self.button_capture_0j)
        layout_h_capture_buttons.addStretch()
        
        layout_h_goto_buttons.setSpacing(10)
        layout_h_goto_buttons.setContentsMargins(-1, 6, -1, 6)
        layout_h_goto_buttons.addWidget(self.button_goto_00)
        layout_h_goto_buttons.addWidget(self.button_goto_i0)
        layout_h_goto_buttons.addWidget(self.button_goto_0j)
        layout_h_goto_buttons.addStretch()
        
        layout_h_goto_buttons2.setSpacing(10)
        layout_h_goto_buttons2.setContentsMargins(-1, 6, -1, 6)
        layout_h_goto_buttons2.addWidget(self.button_goto_center)
        layout_h_goto_buttons2.addWidget(self.button_goto_load)
        layout_h_goto_buttons2.addStretch()
        
        layout_h_automation_buttons.setSpacing(10)
        layout_h_automation_buttons.setContentsMargins(-1, 6, -1, 6)
        layout_h_automation_buttons.addWidget(self.button_start)
        layout_h_automation_buttons.addWidget(self.button_abort)
        layout_h_automation_buttons.addWidget(self.button_abort_all)
        layout_h_automation_buttons.addStretch()
        
        # fill layout for "Sample Info" tab widgets
        layout_v_input_sample.addWidget(self.widget_inputlines)
        layout_v_input_sample.addStretch()
        
        # fill layout for "Stage Controls" tab widgets
        label = QtGui.QLabel("""Use Arrow Keys for X/Y movement
Hold down SHIFT for faster movement speed
Use PgUp/PgDn for Z movement\n
(If it's not working, click the Tab again, it may have
lost focus)""")
        layout_v_input_stages.addWidget(label)
        layout_v_input_stages.addSpacing(15)
        label = QtGui.QLabel("Capture stage positions for devices", self)
        layout_v_input_stages.addWidget(label)
        layout_v_input_stages.addLayout(layout_h_capture_buttons)
        layout_v_input_stages.addSpacing(15)
        label = QtGui.QLabel("Move stage to position", self)
        layout_v_input_stages.addWidget(label)
        layout_v_input_stages.addLayout(layout_h_goto_buttons2)
        layout_v_input_stages.addLayout(layout_h_goto_buttons)
        layout_v_input_stages.addSpacing(15)
        label = QtGui.QLabel("Run automated stage scan and measurements", self)
        layout_v_input_stages.addWidget(label)
        layout_v_input_stages.addLayout(layout_h_automation_buttons)
        layout_v_input_stages.addSpacing(20)
        label = QtGui.QLabel("Scan progress wafer")
        layout_v_input_stages.addWidget(label)
        layout_v_input_stages.addWidget(self.progressbar_wafer)
        layout_v_input_stages.addSpacing(5)
        label = QtGui.QLabel("Scan progress current chip")
        layout_v_input_stages.addWidget(label)
        layout_v_input_stages.addWidget(self.progressbar_chip)
        layout_v_input_stages.addStretch()
        
        # put layouts in frames
        frame_input_sample.setLayout(layout_v_input_sample)
        self.frame_input_stages.setLayout(layout_v_input_stages)
        
        # Tab widgets
        #       input tabs
        input_tabs = QtGui.QTabWidget(main)
        input_tabs.addTab(frame_input_sample, "Sample Info")
        input_tabs.addTab(self.frame_input_stages, "Stage Controls")
        #       output tabs
        output_tabs = QtGui.QTabWidget(main)
        output_tabs.addTab(self.widget_plot, "Results Graph")
        output_tabs.addTab(self.widget_log, "Experiment Log")
        
        # arrange everything and put in main frame
        main_right_col.addWidget(output_tabs)
        main_right_col.addWidget(self.widget_browser)
        self.widget_plot.setMinimumSize(100, 200)

        layout_h_main_columns.setSpacing(10)
        layout_h_main_columns.addWidget(input_tabs)
        layout_h_main_columns.addWidget(main_right_col)
        input_tabs.setMinimumSize(300, 200)
        input_tabs.setMaximumSize(300, 1024)

        main.setLayout(layout_h_main_columns)
        self.setCentralWidget(main)
        self.show()
        self.resize(1000, 800)
    
    
    def _disable_inputs(self):
        '''
        Disables all user input on window and activates abort button. Should be called whenever automated
        scans/measurements are started. Reverse of _enable_inputs(self).
        '''
        self.start_time = dt.now().strftime("%d-%m-%Y__%H-%M-%S")
        print("start time: ", self.start_time)
        '''self.frame_input_stages.removeEventFilter(self)'''
        self.widget_inputlines.setEnabled(False)
        for button in self.BUTTONS:
            button.setEnabled(False)
            button.update()
        self.button_abort_all.setEnabled(True)
        self.widget_browser.show_button.setEnabled(False)
        self.widget_browser.hide_button.setEnabled(False)
        self.widget_browser.clear_button.setEnabled(False)
    
    
    def _enable_inputs(self):
        '''
        Enables all user input on window and deactivates abort button. Should be called whenever automated
        scans/measurements are finished. Reverse of _disable_inputs(self).
        '''
        '''self.frame_input_stages.installEventFilter(self)'''
        self.widget_inputlines.setEnabled(True)
        for button in self.BUTTONS:
            button.setEnabled(True)
        self.button_abort.setEnabled(False)
        self.button_abort_all.setEnabled(False)
        self.widget_browser.show_button.setEnabled(True)
        self.widget_browser.hide_button.setEnabled(True)
        self.widget_browser.clear_button.setEnabled(True)
        self.end_time = dt.now().strftime("%d-%m-%Y__%H-%M-%S")
        print("end time: ", self.end_time)
        print("started at :", self.start_time)
    
    
    # keyboard events
    def eventFilter(self, widget, event):
        '''
        Event filter for keyboard events. Is installed on stages input tab in window. Binds keyboard input
        to commands for motorised stages.
        ArrowKeys: in-plane movement
        SHIFT (hold): increased in-plane movement speed
        PgUp/PgDown: vertical movement
        ESCAPE: all movement emergency stop
        '''
        if (event.type() == QtCore.QEvent.KeyPress and ( widget is self.frame_input_stages or widget in self.BUTTONS )):
            key = event.key()
            if key == QtCore.Qt.Key_Up:
                if not (self.stages._movement_flag & 8) and not (self.stages._movement_flag & 2):
                    self.stage_signals.sig_stage_move_command.emit("north")
                return True
            elif key == QtCore.Qt.Key_Right:
                if  not (self.stages._movement_flag & 4) and not (self.stages._movement_flag & 1):
                    self.stage_signals.sig_stage_move_command.emit("east")
                return True
            elif key == QtCore.Qt.Key_Down:
                if not (self.stages._movement_flag & 2) and not (self.stages._movement_flag & 8):
                    self.stage_signals.sig_stage_move_command.emit("south")
                return True
            elif key == QtCore.Qt.Key_Left:
                if not (self.stages._movement_flag & 1) and not (self.stages._movement_flag & 4):
                    self.stage_signals.sig_stage_move_command.emit("west")
                return True
            elif key == 16777238:
                if not (self.stages._movement_flag & 32) and not (self.stages._movement_flag & 64):
                    self.stage_signals.sig_stage_move_command.emit("up")
                return True
            elif key == 16777239:
                if not (self.stages._movement_flag & 64) and not (self.stages._movement_flag & 32):
                    self.stage_signals.sig_stage_move_command.emit("down")
                return True
            elif key == QtCore.Qt.Key_Shift:
                self.stage_signals.sig_stage_speed_change.emit(1)
                return True
            elif key == QtCore.Qt.Key_Escape:
                self.stages.stage_emergency_stop_call.set()
                sleep(0.1)
                self.stage_signals.sig_stage_emergency_stop.emit()
                return True
        if (event.type() == QtCore.QEvent.KeyRelease and ( widget is self.frame_input_stages or widget in self.BUTTONS )):
            key = event.key()
            if key == QtCore.Qt.Key_Up and not event.isAutoRepeat() and not (self.stages._movement_flag & 2) and not (self.stages._movement_flag == 0):
                self.stage_signals.sig_stage_stop_command.emit("north")
                return True
            elif key == QtCore.Qt.Key_Right and not event.isAutoRepeat() and not (self.stages._movement_flag & 1) and not (self.stages._movement_flag == 0):
                self.stage_signals.sig_stage_stop_command.emit("east")
                return True
            elif key == QtCore.Qt.Key_Down and not event.isAutoRepeat() and not (self.stages._movement_flag & 8) and not (self.stages._movement_flag == 0):
                self.stage_signals.sig_stage_stop_command.emit("south")
                return True
            elif key == QtCore.Qt.Key_Left and not event.isAutoRepeat() and not (self.stages._movement_flag & 4) and not (self.stages._movement_flag == 0):
                self.stage_signals.sig_stage_stop_command.emit("west")
                return True
            elif key == 16777238 and not event.isAutoRepeat() and not (self.stages._movement_flag & 32) and not (self.stages._movement_flag == 0):
                self.stage_signals.sig_stage_stop_command.emit("up")
                return True
            elif key == 16777239 and not event.isAutoRepeat() and not (self.stages._movement_flag & 64) and not (self.stages._movement_flag == 0):
                self.stage_signals.sig_stage_stop_command.emit("down")
                return True
            elif key == QtCore.Qt.Key_Shift:
                self.stage_signals.sig_stage_speed_change.emit(-1)
                return True
        return QtGui.QWidget.eventFilter(self, widget, event)


    # MAIN
    def quit(self, evt=None):
        '''
        Some cleanup before the window is closed. Move stages to home position.
        '''
        try:
            self.abort_all()
        except:
            pass
        self.stages.goto_coords(self.stages._coordinates_center)
        print("exit")
        self.close()


    def updateProgressBars(self, progress_wafer, progress_chip):
            self.progressbar_chip.setValue(progress_chip)
            self.progressbar_wafer.setValue(progress_wafer)


    # BROWSER
    def browser_item_changed(self, item, column):
        '''
        Callback for browser signal.
        Run when a browser item is changed. Updates the plot.
        '''
        if column == 0:
            state = item.checkState(0)
            experiment = self.manager.experiments.with_browser_item(item)
            if state == 0:
                self.plot.removeItem(experiment.curve)
            else:
                experiment.curve.x = self.widget_plot.plot_frame.x_axis
                experiment.curve.y = self.widget_plot.plot_frame.y_axis
                experiment.curve.update()
                self.plot.addItem(experiment.curve)


    def browser_item_menu(self, position):
        '''
        Callback for a browser item menu request.
        '''
        item = self.browser.itemAt(position)

        if item is not None:
            experiment = self.manager.experiments.with_browser_item(item)

            menu = QtGui.QMenu(self)

            # Change Color
            action_change_color = QtGui.QAction(menu)
            action_change_color.setText("Change Color")
            action_change_color.triggered.connect(
                lambda: self.change_color(experiment))
            menu.addAction(action_change_color)

            # Remove
            action_remove = QtGui.QAction(menu)
            action_remove.setText("Remove Graph")
            if self.manager.is_running():
                if self.manager.running_experiment() == experiment:  # Experiment running
                    action_remove.setEnabled(False)
            action_remove.triggered.connect(lambda: self.remove_experiment(experiment))
            menu.addAction(action_remove)

            # Use parameters
            action_use = QtGui.QAction(menu)
            action_use.setText("Use These Parameters")
            action_use.triggered.connect(
                lambda: self.set_parameters(experiment.procedure.parameter_objects()))
            menu.addAction(action_use)
            menu.exec_(self.browser.viewport().mapToGlobal(position))


    # MANAGER
    def remove_experiment(self, experiment):
        '''
        Callback for browser_item_menu entry. Removes the corresponding experiment. Popup window for
        confirmation to avoid accidental data loss.
        '''
        reply = QtGui.QMessageBox.question(self, 'Remove Graph',
                                           "Are you sure you want to remove the graph?",
                                           QtGui.QMessageBox.Yes | QtGui.QMessageBox.No,
                                           QtGui.QMessageBox.No)
        if reply == QtGui.QMessageBox.Yes:
            self.manager.remove(experiment)


    def clear_experiments(self):
        '''
        Callback for GUI browser button "Clear".
        Removes all currently registered experiments.
        '''
        self.manager.clear()


    # PLOTTING
    def new_curve(self, results, color=None, **kwargs):
        if color is None:
            color = pg.intColor(self.browser.topLevelItemCount() % 8)
        return self.widget_plot.new_curve(results, color=color, **kwargs)


    def change_color(self, experiment):
        color = QtGui.QColorDialog.getColor(
            initial=experiment.curve.opts['pen'].color(), parent=self)
        if color.isValid():
            pixelmap = QtGui.QPixmap(24, 24)
            pixelmap.fill(color)
            experiment.browser_item.setIcon(0, QtGui.QIcon(pixelmap))
            experiment.curve.setPen(pg.mkPen(color=color, width=2))


    def show_experiments(self):
        '''
        Callback for GUI browser button "Show".
        Makes all datacurves visible in the plot.
        '''
        root = self.browser.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, QtCore.Qt.Checked)


    def hide_experiments(self):
        '''
        Callback for GUI browser button "Hide".
        Makes all datacurves invisible in the plot.
        '''
        root = self.browser.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, QtCore.Qt.Unchecked)


    # PROCEDURES
    def make_procedure(self):
        '''
        Constructs an instance of the procedure that is registered with the input lines widget of the
        window and returns it.
        '''
        if not isinstance(self.widget_inputlines, InputsWidget):
            raise Exception("ManagedWindow can not make a Procedure"
                            " without a InputsWidget type")
        return self.widget_inputlines.get_procedure()


    #EXPERIMENTS
    def new_experiment(self, results, curve=None):
        '''
        Construct an Experiment instance (Results(procedure, datafile) + corresponding plot curve).
        '''
        if curve is None:
            curve = self.new_curve(results)
        browser_item = BrowserItem(results, curve)
        return Experiment(results, curve, browser_item)


    # SIGNAL HANDLERS
    def abort_all(self):
        '''
        Callback for GUI abort all button.
        Stops all stage movement.
        Sets break flag for producer and kickoff workers and aborts running measurement, if there exists one.
        Removes all queued procdirs from the producer->starter Queue.
        Gives control back to the user (i.e. enables inputs).
        '''
        print("ABORT")
        self.event_abort.set()
        self.stage_signals.sig_stage_emergency_stop.emit()
        sleep(0.1)
        # clear producer pipeline
        while not self.pipeline.empty() or not self.producer_done.is_set():
            self.pipeline.get()
            sleep(0.01)
        # abort PreTest if running
        try:
            self.pretest_worker.stop()
            log.info('PreTest aborted')
        except:
            log.info('No PreTest to abort', exc_info=True)
        self.current_device_passed_pretest.clear()
        # abort Measurement if running
        man_abort = self.abort()
        if not man_abort:
            log.info('Manager had no Gatesweep to abort')
        self._has_no_measurement.set()
        #print("ABORT done")
    
    
    def abort(self):
        '''
        Callback for GUI abort button.
        Stops current measurement. Automated scan is continued with next device.
        '''
        self.button_abort.setEnabled(False)
        #self.button_abort.setText("Resume")
        #self.button_abort.clicked.disconnect()
        #self.button_abort.clicked.connect(self.resume)
        try:
            self.manager.abort()
            return True
        except:
            log.error('Failed to abort experiment', exc_info=True)
            return False
            #self.button_abort.setText("Abort")
            #self.button_abort.clicked.disconnect()
            #self.button_abort.clicked.connect(self.abort)


    def resume(self):
        '''
        Callback for GUI abort button (if binding is changed after an abort call).
        Continues running scheduled measurements.
        Currently not used.
        '''
        #self.button_abort.setText("Abort")
        #self.button_abort.clicked.disconnect()
        #self.button_abort.clicked.connect(self.abort)
        if self.manager.experiments.has_next():
            self.manager.resume()
        else:
            self.button_abort.setEnabled(False)
            self._has_no_measurement.set()


    def queued(self, experiment):
        '''
        Callback for manager signal.
        Run when a new measurement is added to the manager queue.
        '''
        self.button_abort.setEnabled(True)
        self.widget_browser.show_button.setEnabled(True)
        self.widget_browser.hide_button.setEnabled(True)
        self.widget_browser.clear_button.setEnabled(True)


    def running(self, experiment):
        '''
        Callback for manager signal.
        Run when execution of a new measurement is started.
        '''
        self.widget_browser.clear_button.setEnabled(False)


    def abort_returned(self, experiment):
        '''
        Callback for manager signal.
        Run when aborting a measurement is finished.
        '''
        if self.manager.experiments.has_next():
            self.button_abort.setText("Resume")
            self.button_abort.setEnabled(True)
        else:
            self.widget_browser.clear_button.setEnabled(True)


    def finished(self, experiment):
        '''
        Callback for manager signal.
        Run when a measurement is completed.
        Currently not used.
        '''
        if not self.manager.experiments.has_next():
            self.button_abort.setEnabled(False)
            self.widget_browser.clear_button.setEnabled(True)
    
    
    def experiment_finished(self):
        '''
        Callback for manager signal.
        Run when a measurement is completed.
        '''
        self._has_no_measurement.set()


    # ABSTRACTS
    def set_parameters(self, parameters):
        """ This method should be overwritten by the child class. The
        parameters argument is a dictionary of Parameter objects.
        The Parameters should overwrite the GUI values so that a user
        can click "Queue" to capture the same parameters.
        """
        if not isinstance(self.widget_inputlines, InputsWidget):
            raise Exception("ManagedWindow can not set parameters"
                            " without a InputsWidget")
        self.widget_inputlines.set_parameters(parameters)


    def queue(self):
        """

        Abstract method, which must be overridden by the child class.

        Implementations must call ``self.manager.queue(experiment)`` and pass
        an ``experiment``
        (:class:`~pymeasure.experiment.experiment.Experiment`) object which
        contains the
        :class:`~pymeasure.experiment.results.Results` and
        :class:`~pymeasure.experiment.procedure.Procedure` to be run.

        For example:

        .. code-block:: python

            def queue(self):
                filename = unique_filename('results', prefix="data") # from pymeasure.experiment

                procedure = self.make_procedure() # Procedure class was passed at construction
                results = Results(procedure, filename)
                experiment = self.new_experiment(results)

                self.manager.queue(experiment)

        """
        raise NotImplementedError(
            "Abstract method ManagedWindow.queue not implemented")


    def setup_plot(self, plot):
        """
        This method does nothing by default, but can be overridden by the child
        class in order to set up custom options for the plot

        This method is called during the constructor, after all other set up has
        been completed, and is provided as a convenience method to parallel Plotter.

        :param plot: This window's PlotItem instance.

        .. _PlotItem: http://www.pyqtgraph.org/documentation/graphicsItems/plotitem.html
        """
        pass
