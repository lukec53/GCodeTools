# GCodeTools
Tools for manipulating G-Code for 3D printing or CNC machining


## k2p_resume_at_height.py

Written for a Creality K2 Max. Used when a print fails or when you want to change slicer settings part way through a print. This keeps most of the setup code, deletes all of the moves/layers that have been completed, and comments out any lines with a Z height less than your input (to avoid crashes)

**Usage:**
- Before stopping the print, record the current Z position.
- Re-slice the print (optional)
- Export the G-code from the slicer (into the same folder as the python script)
- Run the python script (z argument is in mm):
```bash
python k2p_resume_at_height.py input.gcode output.gcode --z 23.14
```

**Arguments:**
- `input_file`: Input G-code file path
- `output_file`: Output G-code file path
- `--z`: Target Z height to resume from (required)

**Required Machine Macro**
You will need to have this macro in your machine's gcode_macro.cfg
```
[gcode_macro HOME_Z_BACK_CORNER]
gcode:
  G28 X Y ; Home X and Y
  ZDOWN ; Home Z near the bottom of the machine
  G0 Z50 F3000 ; Raise the bed
  G0 X330 F3000 ; Ensure nozzle clears side of the machine
  G0 Y300 F3000 ; Move the nozzle to the rear corner
  PROBE ; Touch the nozzle to the bed
  G0 Z100 F3000 ; Give some clearance to the bed
```
