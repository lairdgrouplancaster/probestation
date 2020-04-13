# probestation
Python code for the custom automated probestation in the labs of Laird group at Lancaster University
(EverBeing C4 probestation with Standa motorized X/Y and Z translation stages).

For a user guide visit the Laird group wiki (http://34.65.175.215/wiki/Automated_probestation_user_guide).

Code has been tested with Python 3.8.2

DEPENDENCIES:
	* pymeasure (Python package)
	* PyQt5 (Python package)
	* libximc (dll needed for controllers of motorized stages, provided by Standa free of charge, search path currently hard coded to "C:/Program Files/ximc/win64/libximc.dll" for Windows OS)

ISSUES
	* pymeasure uses pyqtgraph, which has compatibility issues due to one command in its 'ptime' module. This can be solved by replacing all 'time()' commands in pyqtgraph/ptime with 'process_time()'
