#!/usr/bin/env python3
"""
Combine multiple G-code files into a single program.

Strips start/end g-code from middle segments and sandwiches the printable
sections together.
"""

from pathlib import Path
from typing import List


def load_gcode(path: Path | str) -> List[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()


def save_gcode(path: Path | str, lines: List[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)


def find_first_line(lines: List[str], text: str, start: int = 0) -> int | None:
    """Return the index of the first line containing text, or None."""
    for i in range(start, len(lines)):
        if text in lines[i]:
            return i
    return None


def find_last_line(lines: List[str], text: str) -> int | None:
    """Return the index of the last line containing text, or None."""
    all_idxs = find_lines(lines, text)
    return all_idxs[-1]


def find_lines(lines: List[str], text: str, start: int = 0) -> List[int]:
    """Return every line index containing text."""
    return [i for i in range(start, len(lines)) if text in lines[i]]


def find_object_names(lines: List[str]) -> List[str]:
    lines_with_names = find_lines(lines, 'EXCLUDE_OBJECT_START NAME=')
    unique_names = []
    for line in lines_with_names:
        this_name = lines[line].split('EXCLUDE_OBJECT_START NAME=')[1]
        if not this_name in unique_names:
            unique_names.append(this_name)
    return unique_names


def apply_object_name_prefix(lines: List[str], prefix: str) -> List[int]:
    unique_names = find_object_names(lines)
    for name in unique_names:
        indices_with_this_name = find_lines(lines, name)
        for idx in indices_with_this_name:
            orig_line = lines[idx]
            line_start, line_end = orig_line.split(name)
            lines[idx] = line_start + prefix + name + line_end
    return lines


def remove_start(lines: List[str]) -> List[str]:
    """Get rid of the start lines from a gcode file (heating, prime line, etc)"""
    printstart = find_first_line(lines, ";LAYER_CHANGE")  # The first layer change note indicates the start of the first layer
    print('Removed start of file (' + str(printstart) + ' lines)')
    return lines[printstart:]


def remove_end(lines: List[str]) -> List[str]:
    """Get rid of the finishing lines from a gcode file (cooling, wiping, retract, etc)"""
    printend= find_last_line(lines,'EXCLUDE_OBJECT_END NAME=')
    print('Removed end of file (' + str(len(lines) - printend) + ' lines)')
    return lines[:printend+1] # We want that last line included


def list_all_gcodes_in_folder() -> List[str]:
    # Get a list of all of the G-Code files in the processing folder
    gcodes_dir = Path("/Users/lukas/GitHub/GCodeTools/gcode_combiner/gcodes_to_process")
    input_files = sorted(
        path
        for path in gcodes_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".gcode", ".nc"}
    )
    if not input_files:
        raise FileNotFoundError(f"No .gcode or .nc files found in {gcodes_dir}")
    # Assuming all went well, send them back
    return input_files


def combine_all_gcodes_in_folder() -> List[str]:
    """
    Combine multiple G-code files into one list of lines.
    """
    # Get a list of all of the G-Code files in the processing folder
    input_files = list_all_gcodes_in_folder()
    # Set up the output list
    combined: List[str] = []
    last_index = len(input_files) - 1
    for i, path in enumerate(input_files):
        print('Processing file: ' + str(path).split('/')[-1])
        # Load the file
        curr_file = load_gcode(path)
        # We need to remove the start from every file except the first one
        if i != 0:
            curr_file = remove_start(curr_file)
        # We need to remove the end from every file except the first one
        if i != last_index:
            curr_file = remove_end(curr_file)
        # Rename any objects inside this file, to avoid duplicate names
        curr_file = apply_object_name_prefix(curr_file, str(i) + '_')
        # Add this file to the final combined file
        combined.extend(curr_file)
    # Send the new combined file back
    return combined


def main() -> None:
    combined = combine_all_gcodes_in_folder()
    output_file = Path("/Users/lukas/GitHub/GCodeTools/gcode_combiner/gcodes_to_process/combined.gcode")
    save_gcode(output_file, combined)
    print(f"Wrote {len(combined)} lines to {output_file}")


if __name__ == "__main__":
    main()
