#
# This file is part of the PyMeasure package.
#
# Copyright (c) 2013-2019 PyMeasure Developers
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

import logging

import os
import re
import pyqtgraph as pg

from pymeasure.display.browser import Browser
from pymeasure.display.curves import ResultsCurve, Crosshairs
from pymeasure.display.inputs import BooleanInput, IntegerInput, ListInput, ScientificInput, StringInput
from pymeasure.display.log import LogHandler
from pymeasure.display.Qt import QtCore, QtGui
from pymeasure.experiment import parameters, Procedure
from pymeasure.experiment.results import Results

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


class PlotFrame(QtGui.QFrame):
    """ Combines a PyQtGraph Plot with Crosshairs. Refreshes
    the plot based on the refresh_time, and allows the axes
    to be changed on the fly, which updates the plotted data
    """

    LABEL_STYLE = {'font-size': '10pt', 'font-family': 'Arial', 'color': '#000000'}
    updated = QtCore.QSignal()
    x_axis_changed = QtCore.QSignal(str)
    y_axis_changed = QtCore.QSignal(str)

    def __init__(self, x_axis=None, y_axis=None, refresh_time=0.2, check_status=True, parent=None):
        super().__init__(parent)
        self.refresh_time = refresh_time
        self.check_status = check_status
        self._setup_ui()
        self.change_x_axis(x_axis)
        self.change_y_axis(y_axis)

    def _setup_ui(self):
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: #fff")
        self.setFrameShape(QtGui.QFrame.StyledPanel)
        self.setFrameShadow(QtGui.QFrame.Sunken)
        self.setMidLineWidth(1)

        vbox = QtGui.QVBoxLayout(self)

        self.plot_widget = pg.PlotWidget(self, background='#ffffff')
        self.coordinates = QtGui.QLabel(self)
        self.coordinates.setMinimumSize(QtCore.QSize(0, 20))
        self.coordinates.setStyleSheet("background: #fff")
        self.coordinates.setText("")
        self.coordinates.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignTrailing | QtCore.Qt.AlignVCenter)

        vbox.addWidget(self.plot_widget)
        vbox.addWidget(self.coordinates)
        self.setLayout(vbox)

        self.plot = self.plot_widget.getPlotItem()

        self.crosshairs = Crosshairs(self.plot,
                                     pen=pg.mkPen(color='#AAAAAA', style=QtCore.Qt.DashLine))
        self.crosshairs.coordinates.connect(self.update_coordinates)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_curves)
        self.timer.timeout.connect(self.crosshairs.update)
        self.timer.timeout.connect(self.updated)
        self.timer.start(int(self.refresh_time * 1e3))

    def update_coordinates(self, x, y):
        self.coordinates.setText("(%g, %g)" % (x, y))

    def update_curves(self):
        for item in self.plot.items:
            if isinstance(item, ResultsCurve):
                if self.check_status:
                    if item.results.procedure.status == Procedure.RUNNING:
                        item.update()
                else:
                    item.update()

    def parse_axis(self, axis):
        """ Returns the units of an axis by searching the string
        """
        units_pattern = r"\((?P<units>\w+)\)"
        try:
            match = re.search(units_pattern, axis)
        except TypeError:
            match = None

        if match:
            if 'units' in match.groupdict():
                label = re.sub(units_pattern, '', axis)
                return label, match.groupdict()['units']
        else:
            return axis, None

    def change_x_axis(self, axis):
        for item in self.plot.items:
            if isinstance(item, ResultsCurve):
                item.x = axis
                item.update()
        label, units = self.parse_axis(axis)
        self.plot.setLabel('bottom', label, units=units, **self.LABEL_STYLE)
        self.x_axis = axis
        self.x_axis_changed.emit(axis)

    def change_y_axis(self, axis):
        for item in self.plot.items:
            if isinstance(item, ResultsCurve):
                item.y = axis
                item.update()
        label, units = self.parse_axis(axis)
        self.plot.setLabel('left', label, units=units, **self.LABEL_STYLE)
        self.y_axis = axis
        self.y_axis_changed.emit(axis)


class PlotWidget(QtGui.QWidget):
    """ Extends the PlotFrame to allow different columns
    of the data to be dynamically choosen
    """

    def __init__(self, columns, x_axis=None, y_axis=None, refresh_time=0.2, check_status=True,
                 parent=None):
        super().__init__(parent)
        self.columns = columns
        self.refresh_time = refresh_time
        self.check_status = check_status
        self._setup_ui()
        self._layout()
        if x_axis is not None:
            self.columns_x.setCurrentIndex(self.columns_x.findText(x_axis))
            self.plot_frame.change_x_axis(x_axis)
        if y_axis is not None:
            self.columns_y.setCurrentIndex(self.columns_y.findText(y_axis))
            self.plot_frame.change_y_axis(y_axis)

    def _setup_ui(self):
        self.columns_x_label = QtGui.QLabel(self)
        self.columns_x_label.setMaximumSize(QtCore.QSize(45, 16777215))
        self.columns_x_label.setText('X Axis:')
        self.columns_y_label = QtGui.QLabel(self)
        self.columns_y_label.setMaximumSize(QtCore.QSize(45, 16777215))
        self.columns_y_label.setText('Y Axis:')

        self.columns_x = QtGui.QComboBox(self)
        self.columns_y = QtGui.QComboBox(self)
        for column in self.columns:
            self.columns_x.addItem(column)
            self.columns_y.addItem(column)
        self.columns_x.activated.connect(self.update_x_column)
        self.columns_y.activated.connect(self.update_y_column)

        self.plot_frame = PlotFrame(
            self.columns[0],
            self.columns[1],
            self.refresh_time,
            self.check_status
        )
        self.updated = self.plot_frame.updated
        self.plot = self.plot_frame.plot
        self.columns_x.setCurrentIndex(0)
        self.columns_y.setCurrentIndex(1)

    def _layout(self):
        vbox = QtGui.QVBoxLayout(self)
        vbox.setSpacing(0)

        hbox = QtGui.QHBoxLayout()
        hbox.setSpacing(10)
        hbox.setContentsMargins(-1, 6, -1, 6)
        hbox.addWidget(self.columns_x_label)
        hbox.addWidget(self.columns_x)
        hbox.addWidget(self.columns_y_label)
        hbox.addWidget(self.columns_y)

        vbox.addLayout(hbox)
        vbox.addWidget(self.plot_frame)
        self.setLayout(vbox)

    def sizeHint(self):
        return QtCore.QSize(300, 600)

    def new_curve(self, results, color=pg.intColor(0), **kwargs):
        if 'pen' not in kwargs:
            kwargs['pen'] = pg.mkPen(color=color, width=2)
        if 'antialias' not in kwargs:
            kwargs['antialias'] = False
        curve = ResultsCurve(results,
                             x=self.plot_frame.x_axis,
                             y=self.plot_frame.y_axis,
                             **kwargs
                             )
        curve.setSymbol(None)
        curve.setSymbolBrush(None)
        return curve

    def update_x_column(self, index):
        axis = self.columns_x.itemText(index)
        self.plot_frame.change_x_axis(axis)

    def update_y_column(self, index):
        axis = self.columns_y.itemText(index)
        self.plot_frame.change_y_axis(axis)


class BrowserWidget(QtGui.QWidget):
    def __init__(self, *args, parent=None):
        super().__init__(parent)
        self.browser_args = args
        self._setup_ui()
        self._layout()

    def _setup_ui(self):
        self.browser = Browser(*self.browser_args, parent=self)
        self.clear_button = QtGui.QPushButton('Clear all', self)
        self.clear_button.setEnabled(False)
        self.hide_button = QtGui.QPushButton('Hide all', self)
        self.hide_button.setEnabled(False)
        self.show_button = QtGui.QPushButton('Show all', self)
        self.show_button.setEnabled(False)
        #self.open_button = QtGui.QPushButton('Open', self)
        #self.open_button.setEnabled(True)

    def _layout(self):
        vbox = QtGui.QVBoxLayout(self)
        vbox.setSpacing(0)

        hbox = QtGui.QHBoxLayout()
        hbox.setSpacing(10)
        hbox.setContentsMargins(-1, 6, -1, 6)
        hbox.addWidget(self.show_button)
        hbox.addWidget(self.hide_button)
        hbox.addWidget(self.clear_button)
        hbox.addStretch()
        #hbox.addWidget(self.open_button)

        vbox.addLayout(hbox)
        vbox.addWidget(self.browser)
        self.setLayout(vbox)


class InputsWidget(QtGui.QWidget):
    # tuple of Input classes that do not need an external label
    NO_LABEL_INPUTS = (BooleanInput,)

    def __init__(self, procedure_class, inputs=(), parent=None):
        super().__init__(parent)
        self._procedure_class = procedure_class
        self._procedure = procedure_class()
        self._inputs = inputs
        self._setup_ui()
        self._layout()

    def _setup_ui(self):
        parameter_objects = self._procedure.parameter_objects()
        for name in self._inputs:
            parameter = parameter_objects[name]
            if parameter.ui_class is not None:
                element = parameter.ui_class(parameter)

            elif isinstance(parameter, parameters.FloatParameter):
                element = ScientificInput(parameter)

            elif isinstance(parameter, parameters.IntegerParameter):
                element = IntegerInput(parameter)

            elif isinstance(parameter, parameters.BooleanParameter):
                element = BooleanInput(parameter)

            elif isinstance(parameter, parameters.ListParameter):
                element = ListInput(parameter)

            elif isinstance(parameter, parameters.Parameter):
                element = StringInput(parameter)

            setattr(self, name, element)

    def _layout(self):
        blockspacing = 50
        linespacing = 10
        horspacing = 20
        
        titlefont = QtGui.QFont()
        titlefont.setBold(True)
        titlefont.setWeight(80)
        titlefont.setPointSize(9)
        
        sectionfont = QtGui.QFont()
        sectionfont.setBold(True)
        sectionfont.setWeight(80)
        #sectionfont.setPointSize(9)
        
        vbox = QtGui.QVBoxLayout(self)
        vbox.setSpacing(10)
        
        # sample description block
        vbox_sampleblock = QtGui.QVBoxLayout()
        vbox_sampleblock.setSpacing(5)
        label = QtGui.QLabel()
        label.setFont(titlefont)
        label.setText("Sample description")
        vbox_sampleblock.addWidget(label)
        vbox_sampleblock.addSpacing(linespacing)
        # wafer name
        label = QtGui.QLabel()
        label.setText("Wafer Name")
        vbox_sampleblock.addWidget(label)
        vbox_sampleblock.addWidget(getattr(self, 'wafername'))
        vbox_sampleblock.addSpacing(linespacing)
        # save path
        label = QtGui.QLabel()
        label.setText("Save path")
        vbox_sampleblock.addWidget(label)
        vbox_sampleblock.addWidget(getattr(self, 'savepath'))
        vbox_sampleblock.addSpacing(linespacing)
        vbox_sampleblock.addSpacing(linespacing)
        # number of devices
        #       columns column
        vbox_cols = QtGui.QVBoxLayout()
        vbox_cols.setSpacing(5)
        label = QtGui.QLabel()
        label.setText("#Chip columns")
        vbox_cols.addWidget(label)
        vbox_cols.addWidget(getattr(self, 'chipcols'))
        vbox_cols.addSpacing(linespacing)
        label = QtGui.QLabel()
        label.setText("#Device columns")
        vbox_cols.addWidget(label)
        vbox_cols.addWidget(getattr(self, 'devcols'))
        #       rows column
        vbox_rows = QtGui.QVBoxLayout()
        vbox_rows.setSpacing(5)
        label = QtGui.QLabel()
        label.setText("#Chip rows")
        vbox_rows.addWidget(label)
        vbox_rows.addWidget(getattr(self, 'chiprows'))
        vbox_rows.addSpacing(linespacing)
        label = QtGui.QLabel()
        label.setText("#Device rows")
        vbox_rows.addWidget(label)
        vbox_rows.addWidget(getattr(self, 'devrows'))
        #       combine layout blocks
        hbox_rows_cols = QtGui.QHBoxLayout()
        hbox_rows_cols.addLayout(vbox_cols)
        hbox_rows_cols.addSpacing(horspacing)
        hbox_rows_cols.addLayout(vbox_rows)
        vbox_sampleblock.addLayout(hbox_rows_cols)
        
        # measurement parameters block
        vbox_measurementblock = QtGui.QVBoxLayout()
        vbox_measurementblock.setSpacing(5)
        label = QtGui.QLabel()
        label.setFont(titlefont)
        label.setText("Measurement parameters")
        vbox_measurementblock.addWidget(label)
        vbox_measurementblock.addSpacing(linespacing)
        # bias voltage parameters
        label = QtGui.QLabel()
        label.setFont(sectionfont)
        label.setText("Bias Voltage")
        vbox_measurementblock.addWidget(label)
        #       maximum
        vbox_max = QtGui.QVBoxLayout()
        vbox_max.setSpacing(5)
        label = QtGui.QLabel()
        label.setText("Maximum")
        vbox_max.addWidget(label)
        vbox_max.addWidget(getattr(self, 'V_bias'))
        vbox_max.addSpacing(linespacing)
        label = QtGui.QLabel()
        label.setText("Current limit")
        vbox_max.addWidget(label)
        vbox_max.addWidget(getattr(self, 'I_bias_limit'))
        #       stepsize
        vbox_steps = QtGui.QVBoxLayout()
        vbox_steps.setSpacing(5)
        label = QtGui.QLabel()
        label.setText("Stepsize")
        vbox_steps.addWidget(label)
        vbox_steps.addWidget(getattr(self, 'V_bias_steps'))
        vbox_steps.addSpacing(53)
        #       combine layout blocks
        hbox_bias = QtGui.QHBoxLayout()
        hbox_bias.addLayout(vbox_max)
        hbox_bias.addSpacing(horspacing)
        hbox_bias.addLayout(vbox_steps)
        vbox_measurementblock.addLayout(hbox_bias)
        vbox_measurementblock.addSpacing(linespacing)
        vbox_measurementblock.addSpacing(linespacing)
        # gate voltage parameters
        label = QtGui.QLabel()
        label.setFont(sectionfont)
        label.setText("Gate Voltage")
        vbox_measurementblock.addWidget(label)
        #       range
        vbox_range = QtGui.QVBoxLayout()
        vbox_range.setSpacing(5)
        label = QtGui.QLabel()
        label.setText("Minimum")
        vbox_range.addWidget(label)
        vbox_range.addWidget(getattr(self, 'V_g_min'))
        vbox_range.addSpacing(linespacing)
        label = QtGui.QLabel()
        label.setText("Maximum")
        vbox_range.addWidget(label)
        vbox_range.addWidget(getattr(self, 'V_g_max'))
        #       stepsize
        vbox_steps = QtGui.QVBoxLayout()
        vbox_steps.setSpacing(5)
        vbox_steps.addSpacing(26)
        label = QtGui.QLabel()
        label.setText("Stepsize")
        vbox_steps.addWidget(label)
        vbox_steps.addWidget(getattr(self, 'V_g_steps'))
        vbox_steps.addSpacing(26)
        #       combine layout blocks
        hbox_bias = QtGui.QHBoxLayout()
        hbox_bias.addLayout(vbox_range)
        hbox_bias.addSpacing(horspacing)
        hbox_bias.addLayout(vbox_steps)
        vbox_measurementblock.addLayout(hbox_bias)
        vbox_measurementblock.addSpacing(linespacing)
        vbox_measurementblock.addSpacing(linespacing)
        # delay
        label = QtGui.QLabel()
        label.setText("Measurement delay time")
        vbox_measurementblock.addWidget(label)
        vbox_measurementblock.addWidget(getattr(self, 'delay'))
        vbox_measurementblock.addSpacing(linespacing)
        # NPLC
        #       maximum
        vbox_NPLC_pre = QtGui.QVBoxLayout()
        vbox_NPLC_pre.setSpacing(5)
        label = QtGui.QLabel()
        label.setText("Pretest NPLC")
        vbox_NPLC_pre.addWidget(label)
        vbox_NPLC_pre.addWidget(getattr(self, 'NPLC_pretest'))
        #       stepsize
        vbox_NPLC_meas = QtGui.QVBoxLayout()
        vbox_NPLC_meas.setSpacing(5)
        label = QtGui.QLabel()
        label.setText("Gatesweep NPLC")
        vbox_NPLC_meas.addWidget(label)
        vbox_NPLC_meas.addWidget(getattr(self, 'NPLC_gatesweep'))
        #       combine layout blocks
        hbox_bias = QtGui.QHBoxLayout()
        hbox_bias.addLayout(vbox_NPLC_pre)
        hbox_bias.addSpacing(horspacing)
        hbox_bias.addLayout(vbox_NPLC_meas)
        vbox_measurementblock.addLayout(hbox_bias)

        vbox.addLayout(vbox_sampleblock)
        vbox.addSpacing(blockspacing)
        vbox.addLayout(vbox_measurementblock)
        self.setLayout(vbox)

    def set_parameters(self, parameter_objects):
        for name in self._inputs:
            element = getattr(self, name)
            element.set_parameter(parameter_objects[name])

    def get_procedure(self):
        """ Returns the current procedure """
        self._procedure = self._procedure_class()
        parameter_values = {}
        for name in self._inputs:
            element = getattr(self, name)
            parameter_values[name] = element.parameter.value
        self._procedure.set_parameters(parameter_values)
        return self._procedure


class LogWidget(QtGui.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._layout()

    def _setup_ui(self):
        self.view = QtGui.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.handler = LogHandler()
        self.handler.setFormatter(logging.Formatter(
            fmt='%(asctime)s : %(message)s (%(levelname)s)',
            datefmt='%m/%d/%Y %I:%M:%S %p'
        ))
        self.handler.record.connect(self.view.appendPlainText)

    def _layout(self):
        vbox = QtGui.QVBoxLayout(self)
        vbox.setSpacing(0)

        vbox.addWidget(self.view)
        self.setLayout(vbox)


class ResultsDialog(QtGui.QFileDialog):
    def __init__(self, columns, x_axis=None, y_axis=None, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.x_axis, self.y_axis = x_axis, y_axis
        self.setOption(QtGui.QFileDialog.DontUseNativeDialog, True)
        self._setup_ui()

    def _setup_ui(self):
        preview_tab = QtGui.QTabWidget()
        vbox = QtGui.QVBoxLayout()
        param_vbox = QtGui.QVBoxLayout()
        vbox_widget = QtGui.QWidget()
        param_vbox_widget = QtGui.QWidget()

        self.plot_widget = PlotWidget(self.columns, self.x_axis, self.y_axis, parent=self)
        self.plot = self.plot_widget.plot
        self.preview_param = QtGui.QTreeWidget()
        param_header = QtGui.QTreeWidgetItem(["Name", "Value"])
        self.preview_param.setHeaderItem(param_header)
        self.preview_param.setColumnWidth(0, 150)
        self.preview_param.setAlternatingRowColors(True)

        vbox.addWidget(self.plot_widget)
        param_vbox.addWidget(self.preview_param)
        vbox_widget.setLayout(vbox)
        param_vbox_widget.setLayout(param_vbox)
        preview_tab.addTab(vbox_widget, "Plot Preview")
        preview_tab.addTab(param_vbox_widget, "Run Parameters")
        self.layout().addWidget(preview_tab, 0, 5, 4, 1)
        self.layout().setColumnStretch(5, 1)
        self.setMinimumSize(900, 500)
        self.resize(900, 500)

        self.setFileMode(QtGui.QFileDialog.ExistingFiles)
        self.currentChanged.connect(self.update_plot)

    def update_plot(self, filename):
        self.plot.clear()
        if not os.path.isdir(filename) and filename != '':
            try:
                results = Results.load(str(filename))
            except ValueError:
                return
            except Exception as e:
                raise e

            curve = ResultsCurve(results,
                                 x=self.plot_widget.plot_frame.x_axis,
                                 y=self.plot_widget.plot_frame.y_axis,
                                 pen=pg.mkPen(color=(255, 0, 0), width=1.75),
                                 antialias=True
                                 )
            curve.update()

            self.plot.addItem(curve)

            self.preview_param.clear()
            for key, param in results.procedure.parameter_objects().items():
                new_item = QtGui.QTreeWidgetItem([param.name, str(param)])
                self.preview_param.addTopLevelItem(new_item)
            self.preview_param.sortItems(0, QtCore.Qt.AscendingOrder)
