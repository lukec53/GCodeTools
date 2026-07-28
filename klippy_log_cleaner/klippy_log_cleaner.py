import re

def clean_klippy_log(input_file, output_file):
    spam_patterns = [
        r'retries = 0, cmd = 0xfe 0x5 0x0 0xa1 0xfe 0xfe',
        r'cmd\[0xfe 0x5 0x0 0xa1 0xfe 0xfe\] get response or timeout',
        r'auto_addr_wrapper:.*cmd_485_send_data_with_response timeout',
        r'cmd_485_send_data_with_response timeout',
        r'MOTOR_STALL_MODE DATA=',
        r'MOTOR_SYS_PARAM NUM=1 DATA=1 ID=70',
        r'MOTOR_CHECK_PROTECTION_AFTER_HOME'
    ]
    
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    cleaned = []
    spam_count = 0
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            cleaned.append(line)
            continue
            
        is_spam = any(re.search(pat, line, re.IGNORECASE) for pat in spam_patterns)
        
        if is_spam:
            spam_count += 1
            continue  # skip spam lines
        
        # Keep everything else (including useful timeout or error lines)
        cleaned.append(line)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(cleaned)
    
    print(f"Done! Removed ~{spam_count:,} spam lines.")
    print(f"Original: {len(lines):,} lines → Cleaned: {len(cleaned):,} lines")
    print(f"Clean log saved to: {output_file}")


if __name__ == "__main__":
    clean_klippy_log("logs/klippy.log", "logs/klippy_clean.log")
    # klippy.log has been moved to the logs folder