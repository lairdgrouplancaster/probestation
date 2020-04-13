"""
A script to quickly list all instruments connected to the computer that can communicate via the VISA library.
Can be used to find instrument addresses for the probestation_MAIN application.
"""


from pyvisa import ResourceManager
rm = ResourceManager()
instrument_list = rm.list_resources()

if len(instrument_list)==0:
    print("no instruments found")
else:
    for entry in instrument_list:
        print(entry)
        try:
            inst = rm.open_resource(entry)
            print(inst.query("*IDN?"), "\n")
        except:
            print("not identified\n")
