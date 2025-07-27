"""Log formatting utilities for various output formats."""

import csv
import json
import io
from datetime import datetime
from typing import List, Dict, Any, TextIO

from app.models.logs import LogEntry, LogEntryResponse


class JSONLogFormatter:
    """Formatter for JSON log output."""
    
    @staticmethod
    def format_entry(entry: LogEntry) -> str:
        """Format a single log entry as JSON string."""
        return json.dumps(entry.dict(), default=JSONLogFormatter._json_serializer, ensure_ascii=False)
    
    @staticmethod
    def format_entries(entries: List[LogEntry]) -> str:
        """Format multiple log entries as JSON array."""
        data = [entry.dict() for entry in entries]
        return json.dumps(data, default=JSONLogFormatter._json_serializer, ensure_ascii=False, indent=2)
    
    @staticmethod
    def _json_serializer(obj: Any) -> str:
        """Custom JSON serializer for datetime and other objects."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif hasattr(obj, 'dict'):
            return obj.dict()
        elif hasattr(obj, '__dict__'):
            return obj.__dict__
        return str(obj)


class CSVLogFormatter:
    """Formatter for CSV log output."""
    
    # Standard CSV columns
    COLUMNS = [
        'id', 'timestamp', 'level', 'message', 'module', 'function', 
        'line_number', 'request_id', 'user_id', 'client_ip', 
        'exception_type', 'duration_ms'
    ]
    
    @staticmethod
    def format_entries(entries: List[LogEntry], include_headers: bool = True) -> str:
        """Format log entries as CSV string."""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CSVLogFormatter.COLUMNS)
        
        if include_headers:
            writer.writeheader()
        
        for entry in entries:
            row = CSVLogFormatter._entry_to_row(entry)
            writer.writerow(row)
        
        return output.getvalue()
    
    @staticmethod
    def format_entries_to_file(entries: List[LogEntry], file: TextIO, include_headers: bool = True):
        """Format log entries directly to file."""
        writer = csv.DictWriter(file, fieldnames=CSVLogFormatter.COLUMNS)
        
        if include_headers:
            writer.writeheader()
        
        for entry in entries:
            row = CSVLogFormatter._entry_to_row(entry)
            writer.writerow(row)
    
    @staticmethod
    def _entry_to_row(entry: LogEntry) -> Dict[str, Any]:
        """Convert log entry to CSV row dictionary."""
        return {
            'id': entry.id,
            'timestamp': entry.timestamp.isoformat() if entry.timestamp else '',
            'level': entry.level.value if entry.level else '',
            'message': entry.message or '',
            'module': entry.module or '',
            'function': entry.function or '',
            'line_number': entry.line_number or '',
            'request_id': entry.request_id or '',
            'user_id': entry.user_id or '',
            'client_ip': entry.client_ip or '',
            'exception_type': entry.exception_type or '',
            'duration_ms': entry.duration_ms if entry.duration_ms is not None else ''
        }


class TextLogFormatter:
    """Formatter for human-readable text output."""
    
    @staticmethod
    def format_entry(entry: LogEntry, include_metadata: bool = True) -> str:
        """Format a single log entry as readable text."""
        timestamp = entry.timestamp.strftime('%Y-%m-%d %H:%M:%S') if entry.timestamp else 'N/A'
        level = entry.level.value if entry.level else 'UNKNOWN'
        
        # Basic format
        parts = [
            f"[{timestamp}]",
            f"[{level}]",
            f"[{entry.module}]"
        ]
        
        if entry.function:
            parts.append(f"[{entry.function}:{entry.line_number or '?'}]")
        
        if entry.request_id:
            parts.append(f"[req:{entry.request_id[:8]}]")
        
        basic_line = " ".join(parts) + f" - {entry.message}"
        
        if not include_metadata:
            return basic_line
        
        # Add metadata
        lines = [basic_line]
        
        if entry.user_id:
            lines.append(f"  User: {entry.user_id}")
        
        if entry.client_ip:
            lines.append(f"  IP: {entry.client_ip}")
        
        if entry.duration_ms is not None:
            lines.append(f"  Duration: {entry.duration_ms:.2f}ms")
        
        if entry.exception_type:
            lines.append(f"  Exception: {entry.exception_type}")
            if entry.exception_traceback:
                # Indent traceback lines
                traceback_lines = entry.exception_traceback.split('\n')
                for tb_line in traceback_lines:
                    if tb_line.strip():
                        lines.append(f"    {tb_line}")
        
        if entry.extra_data:
            lines.append("  Extra Data:")
            for key, value in entry.extra_data.items():
                lines.append(f"    {key}: {value}")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_entries(entries: List[LogEntry], include_metadata: bool = True) -> str:
        """Format multiple log entries as readable text."""
        formatted_entries = []
        
        for entry in entries:
            formatted_entries.append(TextLogFormatter.format_entry(entry, include_metadata))
        
        return "\n" + "\n".join(formatted_entries) + "\n"


class WebFormatter:
    """Formatter for web display (HTML-safe)."""
    
    @staticmethod
    def format_entry_for_table(entry: LogEntry) -> Dict[str, str]:
        """Format log entry for HTML table display."""
        return {
            'id': entry.id,
            'timestamp': entry.timestamp.strftime('%Y-%m-%d %H:%M:%S') if entry.timestamp else '',
            'level': entry.level.value if entry.level else '',
            'level_class': f"log-level-{entry.level.value.lower()}" if entry.level else 'log-level-unknown',
            'message': WebFormatter._truncate_message(entry.message),
            'module': entry.module,
            'function': f"{entry.function}:{entry.line_number}" if entry.function else '',
            'request_id': entry.request_id[:8] if entry.request_id else '',
            'user_id': entry.user_id or '',
            'duration': f"{entry.duration_ms:.1f}ms" if entry.duration_ms is not None else '',
            'has_exception': bool(entry.exception_type),
            'has_extra_data': bool(entry.extra_data)
        }
    
    @staticmethod
    def format_entry_for_detail(entry: LogEntry) -> Dict[str, Any]:
        """Format log entry for detailed view."""
        return {
            'id': entry.id,
            'timestamp': entry.timestamp.isoformat() if entry.timestamp else '',
            'timestamp_formatted': entry.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if entry.timestamp else '',
            'level': entry.level.value if entry.level else '',
            'level_class': f"log-level-{entry.level.value.lower()}" if entry.level else 'log-level-unknown',
            'message': entry.message,
            'module': entry.module,
            'function': entry.function,
            'line_number': entry.line_number,
            'request_id': entry.request_id,
            'user_id': entry.user_id,
            'client_ip': entry.client_ip,
            'duration_ms': entry.duration_ms,
            'exception_type': entry.exception_type,
            'exception_traceback': entry.exception_traceback,
            'extra_data': entry.extra_data,
            'extra_data_json': json.dumps(entry.extra_data, indent=2) if entry.extra_data else None
        }
    
    @staticmethod
    def _truncate_message(message: str, max_length: int = 100) -> str:
        """Truncate message for table display."""
        if not message:
            return ''
        
        if len(message) <= max_length:
            return message
        
        return message[:max_length - 3] + '...'


class ConsoleFormatter:
    """Formatter for console output with colors."""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green  
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    @staticmethod
    def format_entry(entry: LogEntry, use_colors: bool = True) -> str:
        """Format log entry for console output."""
        timestamp = entry.timestamp.strftime('%H:%M:%S') if entry.timestamp else '??:??:??'
        level = entry.level.value if entry.level else 'UNKNOWN'
        
        # Color coding
        if use_colors and level in ConsoleFormatter.COLORS:
            level_colored = f"{ConsoleFormatter.COLORS[level]}{level:<8}{ConsoleFormatter.COLORS['RESET']}"
        else:
            level_colored = f"{level:<8}"
        
        # Build components
        components = [
            timestamp,
            level_colored,
            f"{entry.module}:{entry.function or '?'}:{entry.line_number or '?'}"
        ]
        
        if entry.request_id:
            components.append(f"[{entry.request_id[:8]}]")
        
        # Duration if available
        duration_str = ""
        if entry.duration_ms is not None:
            duration_str = f" ({entry.duration_ms:.1f}ms)"
        
        return f"{' '.join(components)} - {entry.message}{duration_str}"


def get_formatter(format_type: str):
    """Get formatter instance by type."""
    formatters = {
        'json': JSONLogFormatter,
        'csv': CSVLogFormatter,
        'txt': TextLogFormatter,
        'text': TextLogFormatter,
        'web': WebFormatter,
        'console': ConsoleFormatter
    }
    
    return formatters.get(format_type.lower())


def export_logs(
    entries: List[LogEntry], 
    format_type: str, 
    include_metadata: bool = True
) -> str:
    """Export logs in specified format."""
    formatter = get_formatter(format_type)
    
    if not formatter:
        raise ValueError(f"Unsupported format: {format_type}")
    
    if format_type.lower() == 'json':
        return formatter.format_entries(entries)
    elif format_type.lower() == 'csv':
        return formatter.format_entries(entries, include_headers=True)
    elif format_type.lower() in ['txt', 'text']:
        return formatter.format_entries(entries, include_metadata)
    else:
        raise ValueError(f"Export not supported for format: {format_type}")