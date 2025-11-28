#!/usr/bin/env python3
"""
G-code Resume Script

This script processes G-code files to resume printing from a specific Z height.
It finds the appropriate layer change, cleans up initial setup code, removes
unsafe moves, and prepares the G-code for resuming a print job.

Usage:
    python start_gcode_at_z_height.py input.gcode output.gcode --z 23.14 --x 0.00 --y 245.00
"""

import argparse
import re
import sys
from typing import List, Tuple, Optional

def printlines(lines: List[str], start_line: int, finish_line: int):
    for i in range(start_line, finish_line+1):
        print(lines[i])


def find_target_layer_with_context(lines: List[str], target_z: float) -> dict[float, int]:
    """
    Find the LAYER_CHANGE marker closest to target_z and return it with context.
    
    Returns a dictionary with 5 layers: the layer closest to target_z, plus
    2 layers below and 2 layers above. The dictionary format is:
        {z_height: line_number, ...}
    
    If there aren't enough layers above or below, it will return fewer entries.
    The middle item in the sorted dictionary will be the layer closest to target_z.
    
    Args:
        lines: List of G-code lines
        target_z: Target Z height to find layer closest to
        
    Returns:
        Dictionary mapping z_height (float) to line_number (int) for up to 5 layers
    """
    # First, collect all layers with their Z heights and line numbers
    all_layers = []
    
    for i in range(len(lines) - 1):
        # Check if this line is a LAYER_CHANGE marker
        if lines[i].strip() == ";LAYER_CHANGE":
            # The next line should contain the Z height
            if i + 1 < len(lines):
                z_line = lines[i + 1].strip()
                # Match pattern: ;Z:23.14 or ;Z:23.0292
                z_match = re.match(r";Z:([\d.]+)", z_line)
                if z_match:
                    layer_z = float(z_match.group(1))
                    all_layers.append((layer_z, i))
    
    if not all_layers:
        return {}
    
    # Find the layer closest to target_z
    closest_layer = min(all_layers, key=lambda x: abs(x[0] - target_z))
    closest_index = all_layers.index(closest_layer)
    
    # Get 2 layers below and 2 layers above
    start_index = max(0, closest_index - 2)
    end_index = min(len(all_layers), closest_index + 3)  # +3 because we want 2 above + the closest itself
    
    # Extract the layers in the range
    context_layers = all_layers[start_index:end_index]
    
    # Convert to dictionary format {z_height: line_number}
    result = {z_height: line_num for z_height, line_num in context_layers}
    
    return result


def decide_target_layer(lines: List[str], target_z: float) -> Optional[Tuple[int, float]]:
    """
    Decide which layer to use based on target_z and return both line number and Z height.
    
    Uses sophisticated logic to find the best layer:
        1. Exact match if available
        2. Layer slightly above target (within allowable_height_above)
        3. Layer slightly below target (within allowable_height_below)
        4. Closest layer if no acceptable match
    
    Args:
        lines: List of G-code lines
        target_z: Target Z height to find layer for
        
    Returns:
        Tuple of (line_number, z_height) if found, None otherwise
    """
    # Define what we are willing to accept
    allowable_height_above = 0.1
    allowable_height_below = 0.05
    # Get the nearest 5 layers (and their line numbers)
    nearby_layers = find_target_layer_with_context(lines, target_z)
    # Make sure there was no error
    if not len(nearby_layers) > 0:
        print(f"No layer found nearby Z={target_z}")
        return None
    
    # Display nearby layers
    print(f"Found {len(nearby_layers)} nearby layers:")
    for z_height in sorted(nearby_layers.keys()):
        line_num = nearby_layers[z_height]
        print(f"  Z={z_height:7.4f} at line {line_num + 1}")
    
    # -------------- Decide which one we want to use --------------
    # Best-case scenario is we find the exact layer
    if target_z in nearby_layers:
        line_number = nearby_layers[target_z]
        print(f"Decided on layer {line_number + 1} with Z={target_z:.4f} (exact match)")
        return (line_number, target_z)
    
    # Next best would be to have a layer slightly above the target
    for z_height, line_number in nearby_layers.items():
        if (z_height > target_z) and (z_height - target_z < allowable_height_above):
            print(f'Decided on layer {line_number + 1} with Z={z_height:.4f} (slightly above target)')
            return (line_number, z_height)
    
    # We haven't found a great option, so let's try a layer just below
    for z_height, line_number in nearby_layers.items():
        if (z_height < target_z) and (target_z - z_height < allowable_height_below):
            print(f'Decided on layer {line_number + 1} with Z={z_height:.4f} (slightly below target)')
            return (line_number, z_height)
    
    # Fallback: use the closest layer
    closest_z = min(nearby_layers.keys(), key=lambda z: abs(z - target_z))
    line_number = nearby_layers[closest_z]
    print(f'Decided on layer {line_number + 1} with Z={closest_z:.4f} (closest available)')
    return (line_number, closest_z)


def find_initial_setup(lines: List[str]) -> Tuple[Optional[int], Optional[int]]:
    """
    Identify the initial setup code that runs before the first layer.
    
    The initial setup is everything between EXECUTABLE_BLOCK_START and
    the first LAYER_CHANGE marker. This includes pre-heating, nozzle cleaning,
    homing, and other startup procedures.
    
    Args:
        lines: List of G-code lines
        
    Returns:
        Tuple of (start_line, end_line) where:
        - start_line: Line number where initial setup begins (EXECUTABLE_BLOCK_START)
        - end_line: Line number right before the first LAYER_CHANGE (inclusive)
        Returns (None, None) if not found
    """
    setup_start = None
    setup_end = None
    
    # Find EXECUTABLE_BLOCK_START
    for i, line in enumerate(lines):
        if "EXECUTABLE_BLOCK_START" in line:
            setup_start = i
            break
    
    # Find the first LAYER_CHANGE marker
    for i, line in enumerate(lines):
        if line.strip() == ";LAYER_CHANGE":
            setup_end = i - 1  # End right before the LAYER_CHANGE
            break
    
    return (setup_start, setup_end)


def expand_start_print_macro(lines: List[str], start_line: int, end_line: int) -> List[str]:
    """
    Expand START_PRINT macro calls with safe content.
    
    Replaces START_PRINT macro calls with the actual macro content, but:
        - Removes unsafe operations (NOZZLE_CLEAR, BOX_NOZZLE_CLEAN, NEXT_HOMEZ_NACCU, G28 Z, PROBE)
        - Replaces G28 with HOME_Z_BACK_CORNER
        - Preserves temperature settings and safe operations
    
    Args:
        lines: List of G-code lines
        start_line: Start of initial setup (inclusive)
        end_line: End of initial setup (inclusive)
        
    Returns:
        Modified list with START_PRINT macros expanded
    """
    result = lines.copy()
    expansions_made = 0
    
    # START_PRINT macro content (safe operations only, with G28 replaced)
    # Based on the START_PRINT macro definition, filtered for resume printing safety
    # This follows the prepare==0 branch, with unsafe operations disabled
    start_print_safe_content = [
        '; ------ START_PRINT macro content (safe operations only) ------\n',
        'G90 ; Set to absolute positioning\n',
        'SET_GCODE_OFFSET Z=0\n',
        'M106 S0  ; Turn off model fan\n',
        'M140 S{params.BED_TEMP} ; Set bed temperature (non-blocking)\n',
        'M104 S{params.EXTRUDER_TEMP} ; Set extruder temperature (non-blocking)\n',
        'SET_VELOCITY_LIMIT ACCEL=5000 ACCEL_TO_DECEL=5000\n',
        'HOME_Z_BACK_CORNER ; Safe homing near bed edges (replaces G28)\n',        
        'M190 S{params.BED_TEMP} ; Set bed temperature and wait (blocking)\n',
        'M109 S{params.EXTRUDER_TEMP} ; Set extruder temperature and wait (blocking)\n',
        'M220 S100 ; Reset Feedrate\n',
        'G21 ; Set units to millimeters\n',
        'SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=10\n',
        'M204 S5000 ; Set acceleration\n',
        'SET_VELOCITY_LIMIT ACCEL_TO_DECEL=5000\n',
        'G92 E0 ; Reset Extruder\n',
        'SET_PIN PIN=extruder_fan VALUE=1\n',
        'SET_TEMPERATURE_FAN_SWITCH TEMPERATURE_FAN=chamber_fan VALUE=1\n',
        '; ------ End of replaced START_PRINT macro content ------\n',
    ]
    
    # Process lines in reverse to avoid index shifting
    for i in range(end_line, start_line - 1, -1):
        if i < len(result):
            line = result[i]
            stripped = line.strip()
            
            # Check if this is a START_PRINT macro call
            if re.match(r'START_PRINT', stripped, re.IGNORECASE):
                # Extract parameters if present
                bed_temp = '55'  # default
                extruder_temp = '220'  # default
                
                bed_match = re.search(r'BED_TEMP=(\d+)', stripped, re.IGNORECASE)
                if bed_match:
                    bed_temp = bed_match.group(1)
                
                ext_match = re.search(r'EXTRUDER_TEMP=(\d+)', stripped, re.IGNORECASE)
                if ext_match:
                    extruder_temp = ext_match.group(1)
                
                # Preserve leading whitespace
                leading_whitespace = line[:len(line) - len(line.lstrip())]
                
                # Create expanded content with parameters substituted
                expanded_lines = []
                for content_line in start_print_safe_content:
                    # Substitute parameters
                    expanded_line = content_line.replace('{params.BED_TEMP}', bed_temp)
                    expanded_line = expanded_line.replace('{params.EXTRUDER_TEMP}', extruder_temp)
                    # Preserve indentation
                    expanded_lines.append(leading_whitespace + expanded_line)
                
                # Replace the START_PRINT line with expanded content
                result[i:i+1] = expanded_lines
                expansions_made += 1
    
    if expansions_made > 0:
        print(f"  Expanded {expansions_made} START_PRINT macro call(s)")
        print(f"  Replaced G28 with HOME_Z_BACK_CORNER in expanded content")
        print(f"  Disabled unsafe operations (NOZZLE_CLEAR, BOX_NOZZLE_CLEAN, NEXT_HOMEZ_NACCU, G28 Z)")
    
    # Also replace any standalone G28 commands that might exist elsewhere
    g28_replacements = 0
    for i in range(start_line, end_line + 1):
        if i < len(result):
            line = result[i]
            stripped = line.strip()
            if re.match(r'^G28\s*$', stripped, re.IGNORECASE):
                leading_whitespace = line[:len(line) - len(line.lstrip())]
                result[i] = leading_whitespace + 'HOME_Z_BACK_CORNER\n'
                g28_replacements += 1
    
    if g28_replacements > 0:
        print(f"  Replaced {g28_replacements} additional G28 command(s) with HOME_Z_BACK_CORNER")
    
    return result


def find_obstruction_checks(lines: List[str], start_line: int, end_line: int) -> List[int]:
    """
    Find obstruction checks in the initial setup code.
    
    Obstruction checks are commands that verify there are no objects on the bed.
    These need to be removed since we have a partially completed print.
    
    Finds:
        - G29 (bed leveling/probing)
        - G30 (probe)
        - Any other common obstruction check patterns
    
    Keeps:
        - G28 (homing) - we still need to home the machine
    
    Args:
        lines: List of G-code lines
        start_line: Start of initial setup (inclusive)
        end_line: End of initial setup (inclusive)
        
    Returns:
        List of line numbers (0-indexed) that contain obstruction checks
    """
    line_numbers = []
    
    # Patterns to find (obstruction checks)
    obstruction_patterns = [
        r'^G29',  # Bed leveling
        r'^G30',  # Probe
        r'^M558',  # Probe configuration
        r'PROBE',  # Any probe-related commands
    ]
    
    # Find lines matching obstruction patterns in the setup section
    for i in range(start_line, end_line + 1):
        if i < len(lines):
            line = lines[i]
            for pattern in obstruction_patterns:
                if re.match(pattern, line.strip(), re.IGNORECASE):
                    line_numbers.append(i)
                    break
    
    return line_numbers


def find_calibration(lines: List[str], start_line: int, end_line: int) -> List[int]:
    """
    Find calibration commands other than homing (G28).
    
    Calibration commands that need to be removed:
        - G29 (bed leveling)
        - G30 (probe)
        - Any auto-calibration sequences
    
    Keeps:
        - G28 (homing) - essential for positioning
    
    Args:
        lines: List of G-code lines
        start_line: Start of initial setup (inclusive)
        end_line: End of initial setup (inclusive)
        
    Returns:
        List of line numbers (0-indexed) that contain calibration commands
    """
    # Define calibration patterns with their meanings
    calibration_patterns = {
        r'^G29': {
            'name': 'G29',
            'meaning': 'Bed leveling/probing - measures bed surface to create mesh',
            'count': 0,
            'line_numbers': []
        },
        r'^G30': {
            'name': 'G30',
            'meaning': 'Single point probe - measures Z height at specific point',
            'count': 0,
            'line_numbers': []
        },
        r'AUTO_CALIBRATE': {
            'name': 'AUTO_CALIBRATE',
            'meaning': 'Automatic calibration sequence - runs full calibration routine',
            'count': 0,
            'line_numbers': []
        },
        r'CALIBRATE': {
            'name': 'CALIBRATE',
            'meaning': 'General calibration command - various calibration operations',
            'count': 0,
            'line_numbers': []
        },
        r'BED_MESH_CALIBRATE': {
            'name': 'BED_MESH_CALIBRATE',
            'meaning': 'Bed mesh calibration - creates mesh map of bed surface',
            'count': 0,
            'line_numbers': []
        },
    }
    
    # Find calibration commands in the setup section
    for i in range(start_line, end_line + 1):
        if i < len(lines):
            line = lines[i]
            for pattern, info in calibration_patterns.items():
                if re.search(pattern, line.strip(), re.IGNORECASE):
                    info['count'] += 1
                    info['line_numbers'].append(i)
                    break
    
    # Print summary of what was found
    print("\nCalibration commands being checked:")
    total_found = 0
    for pattern, info in calibration_patterns.items():
        print(f"  {info['name']} - {info['meaning']}")
        print(f"    Found: {info['count']} instance(s)")
        if info['count'] > 0:
            total_found += info['count']
            # Show first few line numbers if found
            if len(info['line_numbers']) <= 5:
                line_nums_str = ', '.join(str(ln + 1) for ln in info['line_numbers'])
            else:
                first_few = ', '.join(str(ln + 1) for ln in info['line_numbers'][:5])
                line_nums_str = f"{first_few}, ... ({len(info['line_numbers'])} total)"
            print(f"    At lines: {line_nums_str}")
    
    print(f"\nTotal calibration commands found: {total_found}")
    
    # Collect all line numbers to return
    all_line_numbers = []
    for info in calibration_patterns.values():
        all_line_numbers.extend(info['line_numbers'])
    
    # Remove duplicates and sort
    all_line_numbers = sorted(set(all_line_numbers))
    
    return all_line_numbers


def get_mg_command_description(command: str) -> Optional[str]:
    """
    Get a human-readable description for M and G commands.
    
    Args:
        command: The command string (e.g., "M109", "G28", "G92")
        
    Returns:
        Description string if known, None otherwise
    """
    # Dictionary of common M commands and their meanings
    m_commands = {
        'M104': 'Set extruder temperature (non-blocking)',
        'M109': 'Set extruder temperature and wait (blocking)',
        'M140': 'Set bed temperature (non-blocking)',
        'M141': 'Set chamber temperature (non-blocking)',
        'M190': 'Set bed temperature and wait (blocking)',
        'M106': 'Set fan speed',
        'M107': 'Turn off fan',
        'M73': 'Set print progress',
        'M83': 'Set extruder to relative mode',
        'M82': 'Set extruder to absolute mode',
        'M204': 'Set acceleration',
        'M205': 'Set advanced settings',
        'M220': 'Set speed factor override percentage',
        'M221': 'Set extrude factor override percentage',
    }
    
    # Dictionary of common G commands and their meanings
    g_commands = {
        'G28': 'Home all axes',
        'G29': 'Bed leveling/probing',
        'G30': 'Single point probe',
        'G90': 'Set to absolute positioning',
        'G91': 'Set to relative positioning',
        'G92': 'Set position (offset current position)',
        'G21': 'Set units to millimeters',
        'G20': 'Set units to inches',
    }
    
    # Extract the base command (M### or G###)
    command_match = re.match(r'^([MG]\d+)', command.upper())
    if command_match:
        base_command = command_match.group(1)
        if base_command in m_commands:
            return m_commands[base_command]
        if base_command in g_commands:
            return g_commands[base_command]
    
    return None


def add_explanatory_comments(lines: List[str], start_line: int, end_line: int) -> List[str]:
    """
    Add explanatory comments to M and G commands (excluding G0 and G1) in the setup code.
    
    This adds comments at the end of lines to explain what each command does,
    making it easier for human readers to understand what setup will run.
    G0 and G1 are excluded because they are movement commands that are self-explanatory.
    
    Args:
        lines: List of G-code lines
        start_line: Start of initial setup (inclusive)
        end_line: End of initial setup (inclusive)
        
    Returns:
        Modified list with explanatory comments added
    """
    result = lines.copy()
    
    for i in range(start_line, end_line + 1):
        if i < len(result):
            line = result[i]
            stripped = line.strip()
            
            # Skip empty lines and lines that are already comments
            if not stripped or stripped.startswith(';'):
                continue
            
            # Skip if line already has a comment
            if ';' in stripped:
                continue
            
            description = None
            
            # Check if line starts with M command (any M command)
            m_match = re.match(r'^(M\d+)', stripped, re.IGNORECASE)
            if m_match:
                description = get_mg_command_description(m_match.group(1))
            
            # Check if line starts with G command, but exclude G0 and G1
            if not description:
                g_match = re.match(r'^(G\d+)', stripped, re.IGNORECASE)
                if g_match:
                    g_number_str = g_match.group(1)[1:]  # Get number part
                    g_number = int(g_number_str) if g_number_str.isdigit() else 0
                    # Include G2, G3, G4, etc. but exclude G0 and G1
                    if g_number >= 2:
                        description = get_mg_command_description(g_match.group(1))
            
            # Add description as comment if we found one
            if description:
                # Preserve the original line and add comment
                result[i] = line.rstrip() + ' ; ' + description + '\n'
    
    return result


def check_extruder_mode_consistency(lines: List[str], setup_start: int, setup_end: int, 
                                     target_layer_line: int) -> dict:
    """
    Check if extruder positioning mode is properly configured for resuming print.
    
    Verifies:
        1. What extruder mode is set in setup (M83 = relative, M82 = absolute)
        2. If G92 E command exists to set/reset extruder position
        3. What E values are used in the first layer (to infer expected mode)
        4. Consistency between setup mode and layer expectations
    
    Args:
        lines: List of G-code lines
        setup_start: Start of initial setup (inclusive)
        setup_end: End of initial setup (inclusive)
        target_layer_line: Line number of target LAYER_CHANGE marker
        
    Returns:
        Dictionary with check results and recommendations
    """
    result = {
        'setup_mode': None,  # 'relative' or 'absolute' or None
        'has_g92_e': False,
        'g92_e_line': None,
        'first_layer_e_values': [],
        'first_layer_suggests_relative': None,
        'issues': [],
        'recommendations': []
    }
    
    # Check setup code for extruder mode commands
    for i in range(setup_start, setup_end + 1):
        if i < len(lines):
            line = lines[i].strip()
            if not line or line.startswith(';'):
                continue
            
            # Check for M83 (relative) or M82 (absolute)
            if re.match(r'^M83', line, re.IGNORECASE):
                result['setup_mode'] = 'relative'
            elif re.match(r'^M82', line, re.IGNORECASE):
                result['setup_mode'] = 'absolute'
            
            # Check for G92 E command (sets extruder position)
            if re.search(r'G92\s+.*E', line, re.IGNORECASE):
                result['has_g92_e'] = True
                result['g92_e_line'] = i
                # Extract E value if present
                e_match = re.search(r'E([\d.]+)', line, re.IGNORECASE)
                if e_match:
                    result['g92_e_value'] = float(e_match.group(1))
    
    # Check first few lines of target layer for E values
    # Look at first 50 lines after LAYER_CHANGE to get a sense of E values
    layer_start = target_layer_line
    layer_end = min(len(lines), layer_start + 50)
    
    for i in range(layer_start, layer_end):
        if i < len(lines):
            line = lines[i].strip()
            if not line or line.startswith(';'):
                continue
            
            # Look for G1/G0 commands with E values
            if (line.startswith('G1') or line.startswith('G0')) and 'E' in line.upper():
                e_match = re.search(r'E([\d.]+)', line, re.IGNORECASE)
                if e_match:
                    e_value = float(e_match.group(1))
                    result['first_layer_e_values'].append(e_value)
    
    # Analyze E values to infer expected mode
    if result['first_layer_e_values']:
        # In relative mode, E values are typically small increments (0.1-5.0)
        # In absolute mode, E values are typically cumulative and larger
        first_e = result['first_layer_e_values'][0]
        max_e = max(result['first_layer_e_values'])
        
        # If first E value is very small (< 1.0) and values increase gradually,
        # it's likely relative mode
        # If first E value is large (> 10.0) or values jump significantly,
        # it's likely absolute mode
        if first_e < 1.0 and max_e < 10.0:
            result['first_layer_suggests_relative'] = True
        elif first_e > 10.0 or max_e > 100.0:
            result['first_layer_suggests_relative'] = False
    
    # Check for issues and generate recommendations
    if result['setup_mode'] is None:
        result['issues'].append("No extruder mode set in setup (M83 or M82 not found)")
        result['recommendations'].append("Add M83 (relative mode) or M82 (absolute mode) to setup")
    
    if not result['has_g92_e']:
        result['issues'].append("No G92 E command found to reset extruder position")
        result['recommendations'].append("Add 'G92 E0' before first layer to reset extruder position")
    
    # Check consistency
    if result['setup_mode'] == 'relative' and result['first_layer_suggests_relative'] == False:
        result['issues'].append("Setup uses relative mode (M83) but first layer E values suggest absolute mode")
        result['recommendations'].append("Verify extruder mode matches first layer expectations")
    elif result['setup_mode'] == 'absolute' and result['first_layer_suggests_relative'] == True:
        result['issues'].append("Setup uses absolute mode (M82) but first layer E values suggest relative mode")
        result['recommendations'].append("Verify extruder mode matches first layer expectations")
    
    return result


def disable_unsafe_moves(lines: List[str], unsafe_moves: List[Tuple[int, str]]) -> List[str]:
    """
    Comment out unsafe move lines to disable them.
    
    Comments out each unsafe move line and adds a note explaining why it was disabled.
    This prevents the move from executing while preserving it for review.
    
    Args:
        lines: List of G-code lines
        unsafe_moves: List of tuples (line_number, line_content) for unsafe moves
        
    Returns:
        Modified list with unsafe moves commented out
    """
    result = lines.copy()
    # Sort by line number in descending order to avoid index shifting issues
    unsafe_moves_sorted = sorted(unsafe_moves, key=lambda x: x[0], reverse=True)
    
    for line_num, _ in unsafe_moves_sorted:
        if line_num < len(result):
            line = result[line_num]
            # Only comment if it's not already a comment
            stripped = line.lstrip()
            if stripped and not stripped.startswith(';'):
                # Preserve leading whitespace, add semicolon and explanation
                leading_whitespace = line[:len(line) - len(line.lstrip())]
                # Remove trailing newline, add semicolon and explanation comment
                stripped_no_newline = stripped.rstrip('\n\r')
                result[line_num] = leading_whitespace + ';' + stripped_no_newline + ' ; Disabled potentially unsafe move to avoid contacting partially completed print\n'
    
    return result


def delete_lines(lines: List[str], line_numbers: List[int]) -> List[str]:
    """
    Delete specified lines from the G-code.
    
    This function removes lines by their line numbers. Line numbers should be
    provided in any order, but deletion happens from highest to lowest to
    avoid index shifting issues.
    
    Args:
        lines: List of G-code lines
        line_numbers: List of line numbers (0-indexed) to delete
        
    Returns:
        Modified list with specified lines removed
    """
    # Create a set for fast lookup and remove duplicates
    lines_to_delete = set(line_numbers)
    
    # Filter out lines that are marked for deletion
    result = [line for i, line in enumerate(lines) if i not in lines_to_delete]
    
    return result


def find_unsafe_moves_in_layer(lines: List[str], layer_start_line: int, target_z: float, num_lines_to_check: int = 100) -> List[Tuple[int, str]]:
    """
    Find unsafe moves at the start of a layer that could drag across the bed.
    
    Checks the first moves in a layer to ensure they include safe Z positioning
    before any XY moves. This prevents dragging the nozzle across the bed.
    
    Args:
        lines: List of G-code lines
        layer_start_line: Line number where layer starts (LAYER_CHANGE marker)
        target_z: Target Z height (moves below this are unsafe)
        num_lines_to_check: Number of lines to check after layer start
        
    Returns:
        List of tuples (line_number, line_content) for unsafe moves found
    """
    unsafe_moves = []
    current_z = None
    first_xy_move_found = False
    
    # Check first moves in the layer
    for i in range(layer_start_line, min(layer_start_line + num_lines_to_check, len(lines))):
        if i < len(lines):
            line = lines[i].strip()
            
            # Skip comments and empty lines
            if not line or line.startswith(';'):
                continue
            
            # Extract Z coordinate from any move command
            z_match = re.search(r'Z([\d.]+)', line, re.IGNORECASE)
            if z_match:
                current_z = float(z_match.group(1))
            
            # Check for G0, G1, G2, G3 moves
            is_move_command = (line.startswith('G0') or line.startswith('G1') or 
                              line.startswith('G2') or line.startswith('G3'))
            
            if is_move_command:
                # Check if this move has XY coordinates
                has_xy = re.search(r'[XY][\d.]', line, re.IGNORECASE)
                
                # If this is the first XY move and Z is not set to a safe height, it's unsafe
                if has_xy and not first_xy_move_found:
                    first_xy_move_found = True
                    # If Z is not explicitly set in this move and current Z is unknown or low
                    if not z_match:
                        if current_z is None or current_z < target_z:
                            unsafe_moves.append((i, line))
                    elif z_match:
                        move_z = float(z_match.group(1))
                        if move_z < target_z:
                            unsafe_moves.append((i, line))
                # If Z is set but below target, it's unsafe
                elif z_match:
                    move_z = float(z_match.group(1))
                    if move_z < target_z:
                        unsafe_moves.append((i, line))
                # If we have XY moves when Z is below target, it's unsafe
                elif has_xy and current_z is not None and current_z < target_z:
                    unsafe_moves.append((i, line))
    
    return unsafe_moves


def find_unsafe_moves(lines: List[str], start_line: int, end_line: int, target_z: float) -> List[Tuple[int, str]]:
    """
    Find unsafe moves in the initial setup code.
    
    Unsafe moves are those that could contact the partially completed print:
        1. G0/G1/G2/G3 moves with Z < target layer height
        2. XY moves (including arcs) when Z is below target layer height
        3. Arc moves (G2/G3) that could contact the print
    
    Args:
        lines: List of G-code lines
        start_line: Start of initial setup (inclusive)
        end_line: End of initial setup (inclusive)
        target_z: Target Z height (moves below this are unsafe)
        
    Returns:
        List of tuples (line_number, line_content) for unsafe moves found
    """
    unsafe_moves = []
    current_z = None
    
    # Track current Z position as we parse
    for i in range(start_line, min(end_line + 1, len(lines))):
        line = lines[i].strip()
        
        # Skip comments and empty lines
        if not line or line.startswith(';'):
            continue
        
        # Extract Z coordinate from any move command
        z_match = re.search(r'Z([\d.]+)', line, re.IGNORECASE)
        if z_match:
            current_z = float(z_match.group(1))
        
        # Check for G0, G1, G2, G3 moves (linear and arc moves)
        is_move_command = (line.startswith('G0') or line.startswith('G1') or 
                          line.startswith('G2') or line.startswith('G3'))
        
        if is_move_command:
            # Check if this move has Z < target_z
            if z_match:
                move_z = float(z_match.group(1))
                if move_z < target_z:
                    unsafe_moves.append((i, line))
            # Check if this is an XY move (or arc) when Z is below target
            elif current_z is not None and current_z < target_z:
                # Check if line has X, Y coordinates, or arc parameters (I, J, R)
                # G2/G3 arc moves use I, J for center offset or R for radius
                if (re.search(r'[XY][\d.]', line, re.IGNORECASE) or
                    re.search(r'[IJR][\d.]', line, re.IGNORECASE)):
                    unsafe_moves.append((i, line))
            # Special case: G2/G3 with Z but no explicit Z coordinate means it's moving in Z
            # If current Z is below target, this could be unsafe
            elif (line.startswith('G2') or line.startswith('G3')):
                if current_z is not None and current_z < target_z:
                    # Arc move when Z is below target - could be unsafe
                    unsafe_moves.append((i, line))
    
    return unsafe_moves


def find_intermediate_code_range(setup_end: int, target_layer_line: int) -> Tuple[int, int]:
    """
    Find the range of lines to delete between setup and target layer.
    
    Args:
        setup_end: Last line of initial setup (inclusive)
        target_layer_line: Line number of target LAYER_CHANGE marker
        
    Returns:
        Tuple of (start_line, end_line) for the range to delete (both inclusive)
    """
    # Delete everything from setup_end + 1 to target_layer_line - 1
    delete_start = setup_end + 1
    delete_end = target_layer_line - 1
    return (delete_start, delete_end)


def delete_intermediate_code(lines: List[str], setup_end: int, target_layer_line: int) -> List[str]:
    """
    Delete all code between the end of initial setup and the target layer change.
    
    This removes all the layers that were already printed, keeping only:
        1. Header and initial setup code
        2. The target layer and everything after it
    
    Args:
        lines: List of G-code lines
        setup_end: Last line of initial setup (inclusive)
        target_layer_line: Line number of target LAYER_CHANGE marker
        
    Returns:
        Modified list with intermediate code removed
    """
    # Keep everything up to and including setup_end
    # Then skip to target_layer_line
    result = lines[:setup_end + 1]
    
    # Add everything from target_layer_line onwards
    if target_layer_line < len(lines):
        result.extend(lines[target_layer_line:])
    
    return result


def process_gcode(input_file: str, output_file: str, target_z: float, x_pos: float, y_pos: float) -> dict:
    """
    Main processing function that orchestrates the G-code modification workflow.
    
    Steps:
        1. Read the input G-code file
        2. Find the target layer at or below target_z
        3. Find the initial setup code
        4. Process homing and unsafe macros
        5. Remove obstruction checks
        6. Remove calibration
        7. Add explanatory comments to M/G commands
        8. Check extruder mode consistency
        9. Check for unsafe moves
        10. Check for unsafe moves at layer start
        11. Delete intermediate code
        12. Write the modified G-code to output file
    
    Args:
        input_file: Path to input G-code file
        output_file: Path to output G-code file
        target_z: Target Z height to resume from
        x_pos: X position where print was stopped (for reference)
        y_pos: Y position where print was stopped (for reference)
        
    Returns:
        Dictionary with processing summary
    """
    # Read input file
    print(f"Reading G-code from: {input_file}")
    with open(input_file, 'r') as f:
        lines = f.readlines()
    
    print(f"Total lines: {len(lines)}")
    
    # Step 1: Find target layer
    print(f"\nStep 1: Finding layer near Z={target_z}")
    result = decide_target_layer(lines, target_z)
    if result is None:
        raise ValueError(f"No acceptable layer found near Z={target_z}")
    
    target_layer_line, layer_z = result
    print(f"\nUsing target layer: Z={layer_z:.4f} at line {target_layer_line + 1}")
    
    # Step 2: Find initial setup
    print("\nStep 2: Finding initial setup code")
    setup_start, setup_end = find_initial_setup(lines)
    if setup_start is None or setup_end is None:
        raise ValueError("Could not find initial setup code (EXECUTABLE_BLOCK_START or LAYER_CHANGE)")
    
    print(f"Initial setup: lines {setup_start + 1} to {setup_end + 1}")
    
    # Step 3: Expand START_PRINT macro and process homing
    print("\nStep 3: Expanding START_PRINT macro and processing homing")
    lines = expand_start_print_macro(lines, setup_start, setup_end)
    
    # Step 4: Find for possible collisions in the initial setup
    print("\nStep 4: Finding possible collisions in the initial setup")
    # Recalculate setup positions after previous modifications
    setup_start, setup_end = find_initial_setup(lines)
    if setup_start is None or setup_end is None:
        raise ValueError("Could not find setup after previous modifications")
    
    obstruction_lines = find_obstruction_checks(lines, setup_start, setup_end)
    if obstruction_lines:
        print(f"Found {len(obstruction_lines)} possible collision lines:")
        for line_num in obstruction_lines:
            print(f"  Line {line_num + 1}: {lines[line_num].strip()}")
        if len(obstruction_lines) > 10:
            print(f"  ... and {len(obstruction_lines) - 10} more")
        lines = delete_lines(lines, obstruction_lines)
        print(f"Removed {len(obstruction_lines)} possible collision lines")
    else:
        print("No collisions found")
    
    # Step 5: Find and remove calibration
    print("\nStep 5: Finding calibration commands")
    # Recalculate setup positions after previous deletions
    setup_start, setup_end = find_initial_setup(lines)
    if setup_start is None or setup_end is None:
        raise ValueError("Could not find setup after previous modifications")
    
    calibration_lines = find_calibration(lines, setup_start, setup_end)
    if calibration_lines:
        print(f"Found {len(calibration_lines)} calibration command lines:")
        for line_num in calibration_lines:
            print(f"  Line {line_num + 1}: {lines[line_num].strip()}")
        lines = delete_lines(lines, calibration_lines)
        print(f"Removed {len(calibration_lines)} calibration command lines")
    else:
        print("No calibration commands found")
    
    # Step 6: Add explanatory comments to M/G commands in setup (excluding G0/G1)
    print("\nStep 6: Adding explanatory comments to M and G commands in setup (excluding G0/G1)")
    # Recalculate positions after removals
    setup_start_new, setup_end_new = find_initial_setup(lines)
    if setup_start_new is None or setup_end_new is None:
        raise ValueError("Could not find setup after modifications")
    
    lines_before = lines.copy()
    lines = add_explanatory_comments(lines, setup_start_new, setup_end_new)
    
    # Count how many comments were added
    comments_added = 0
    for i in range(setup_start_new, setup_end_new + 1):
        if i < len(lines) and i < len(lines_before):
            if lines[i] != lines_before[i] and ' ; ' in lines[i]:
                comments_added += 1
    
    if comments_added > 0:
        print(f"Added explanatory comments to {comments_added} M/G command lines")
    else:
        print("No M/G commands found to add comments to (excluding G0/G1)")
    
    # Step 7: Check extruder mode consistency
    print("\nStep 7: Checking extruder positioning mode consistency")
    # Recalculate positions after commenting
    setup_start_new, setup_end_new = find_initial_setup(lines)
    if setup_start_new is None or setup_end_new is None:
        raise ValueError("Could not find setup after modifications")
    
    extruder_check = check_extruder_mode_consistency(lines, setup_start_new, setup_end_new, target_layer_line)
    
    print(f"  Setup extruder mode: {extruder_check['setup_mode'] or 'NOT SET'}")
    print(f"  G92 E command found: {'Yes' if extruder_check['has_g92_e'] else 'No'}")
    if extruder_check['has_g92_e'] and 'g92_e_value' in extruder_check:
        print(f"  G92 E value: {extruder_check['g92_e_value']}")
    
    if extruder_check['first_layer_e_values']:
        print(f"  First layer E values: {extruder_check['first_layer_e_values'][:5]}...")
        if extruder_check['first_layer_suggests_relative'] is not None:
            mode_str = "relative" if extruder_check['first_layer_suggests_relative'] else "absolute"
            print(f"  First layer suggests: {mode_str} mode")
    
    if extruder_check['issues']:
        print(f"\n  WARNING: Found {len(extruder_check['issues'])} potential issues:")
        for issue in extruder_check['issues']:
            print(f"    - {issue}")
    
    if extruder_check['recommendations']:
        print(f"\n  Recommendations:")
        for rec in extruder_check['recommendations']:
            print(f"    - {rec}")
    
    if not extruder_check['issues']:
        print("  ✓ Extruder mode appears to be properly configured")
    
    # Step 8: Find unsafe moves
    print("\nStep 8: Finding unsafe moves")
    # Recalculate positions after commenting
    setup_start_new, setup_end_new = find_initial_setup(lines)
    if setup_start_new is None or setup_end_new is None:
        raise ValueError("Could not find setup after modifications")
    
    unsafe_moves = find_unsafe_moves(lines, setup_start_new, setup_end_new, target_z)
    if unsafe_moves:
        print(f"WARNING: Found {len(unsafe_moves)} potentially unsafe moves:")
        for line_num, line_content in unsafe_moves[:10]:  # Show first 10
            print(f"  Line {line_num + 1}: {line_content}")
        if len(unsafe_moves) > 10:
            print(f"  ... and {len(unsafe_moves) - 10} more")
        # Comment out unsafe move lines to disable them
        lines = disable_unsafe_moves(lines, unsafe_moves)
        print(f"Commented out {len(unsafe_moves)} unsafe move lines to disable them")
    else:
        print("No unsafe moves detected")
    
    # Step 9: Check for unsafe moves at start of target layer
    print("\nStep 9: Checking for unsafe moves at start of target layer")
    # Recalculate target_layer_line (line numbers may have shifted after removals)
    result = decide_target_layer(lines, target_z)
    if result is None:
        raise ValueError("Could not find target layer after modifications")
    
    target_layer_line, _ = result
    
    # Check first moves in the layer for unsafe XY moves without safe Z
    layer_unsafe_moves = find_unsafe_moves_in_layer(lines, target_layer_line, target_z)
    if layer_unsafe_moves:
        print(f"WARNING: Found {len(layer_unsafe_moves)} potentially unsafe moves at layer start:")
        for line_num, line_content in layer_unsafe_moves[:10]:  # Show first 10
            print(f"  Line {line_num + 1}: {line_content}")
        if len(layer_unsafe_moves) > 10:
            print(f"  ... and {len(layer_unsafe_moves) - 10} more")
        # Comment out unsafe moves at layer start
        lines = disable_unsafe_moves(lines, layer_unsafe_moves)
        print(f"Commented out {len(layer_unsafe_moves)} unsafe move lines at layer start")
        
        # Add a safe Z move before the layer if needed
        # Find the first non-comment line after LAYER_CHANGE
        first_move_line = None
        for i in range(target_layer_line, min(target_layer_line + 20, len(lines))):
            if i < len(lines):
                line = lines[i].strip()
                if line and not line.startswith(';') and (line.startswith('G0') or line.startswith('G1')):
                    first_move_line = i
                    break
        
        if first_move_line is not None:
            # Check if first move has Z coordinate
            first_move = lines[first_move_line].strip()
            if not re.search(r'Z([\d.]+)', first_move, re.IGNORECASE):
                # Insert a safe Z move before the first move
                leading_whitespace = lines[first_move_line][:len(lines[first_move_line]) - len(lines[first_move_line].lstrip())]
                safe_z_move = leading_whitespace + f'G1 Z{target_z + 1:.2f} F30000 ; Safe Z move before layer start\n'
                lines.insert(first_move_line, safe_z_move)
                print(f"Added safe Z move (Z={target_z + 1:.2f}) before first layer move")
    else:
        print("No unsafe moves detected at layer start")
    
    # Step 10: Find and delete intermediate code
    print("\nStep 10: Finding intermediate code to delete")
    # Recalculate setup_end after all modifications
    setup_start_new, setup_end_new = find_initial_setup(lines)
    if setup_end_new is None:
        raise ValueError("Could not find setup end after modifications")
    
    setup_end = setup_end_new
    
    # Recalculate target_layer_line again (may have shifted from inserted Z move)
    result = decide_target_layer(lines, target_z)
    if result is None:
        raise ValueError("Could not find target layer after modifications")
    
    target_layer_line, _ = result
    
    # Find the range of lines to delete
    delete_start, delete_end = find_intermediate_code_range(setup_end, target_layer_line)
    if delete_start <= delete_end:
        intermediate_lines = list(range(delete_start, delete_end + 1))
        print(f"Found {len(intermediate_lines)} intermediate lines to delete (lines {delete_start + 1} to {delete_end + 1})")
        lines_before = len(lines)
        lines = delete_lines(lines, intermediate_lines)
        lines_after = len(lines)
        deleted_lines = lines_before - lines_after
    else:
        print("No intermediate code to delete")
        deleted_lines = 0
    
    print(f"Deleted {deleted_lines} lines between setup and target layer")
    
    # Step 11: Write output file
    print(f"\nStep 11: Writing modified G-code to: {output_file}")
    with open(output_file, 'w') as f:
        f.writelines(lines)
    
    print(f"Output file written successfully")
    
    # Return summary
    return {
        'input_lines': len(lines),
        'output_lines': len(lines),
        'target_layer_line': target_layer_line + 1,
        'target_z': layer_z if 'layer_z' in locals() else None,
        'unsafe_moves': len(unsafe_moves),
        'deleted_lines': deleted_lines
    }


def main():
    """
    Main entry point for the script.
    
    Parses command-line arguments and calls the processing function.
    """
    parser = argparse.ArgumentParser(
        description='Process G-code to resume printing from a specific Z height',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Example:
        python start_gcode_at_z_height.py input.gcode output.gcode --z 23.14 --x 0.00 --y 245.00
    """
    )
    
    parser.add_argument('input_file', help='Input G-code file path')
    parser.add_argument('output_file', help='Output G-code file path')
    parser.add_argument('--z', '--z-height', type=float, required=True,
                        help='Target Z height to resume from')
    parser.add_argument('--x', '--x-pos', type=float, default=0.0,
                        help='X position where print stopped (for reference)')
    parser.add_argument('--y', '--y-pos', type=float, default=0.0,
                        help='Y position where print stopped (for reference)')
    
    args = parser.parse_args()
    
    try:
        summary = process_gcode(
            args.input_file,
            args.output_file,
            args.z,
            args.x,
            args.y
        )
        
        print("\n" + "="*60)
        print("Processing Summary")
        print("="*60)
        print(f"Target layer: Line {summary['target_layer_line']}, Z={summary['target_z']}")
        print(f"Unsafe moves found: {summary['unsafe_moves']}")
        print(f"Lines deleted: {summary['deleted_lines']}")
        print(f"Output file: {args.output_file}")
        print("="*60)
        
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
