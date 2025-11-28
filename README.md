# GCodeTools
Tools for manipulating G-Code for 3D printing or CNC machining


## k2p_resume_at_height.py

Used when a 3D print either fails or you want to change slicer settings after the print is already partially completed. This keeps the setup code, but deletes all of the moves/layers that have been completed.

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
