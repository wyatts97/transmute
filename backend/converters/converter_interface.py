import os
from core import media_type_aliases
from typing import Optional


def _normalize_converter_media_type(media_type: str) -> str:
    """Normalize input/output types for converter execution."""
    normalized = media_type.lower()
    if normalized == "webvideo":
        return "mp4"
    if normalized == "webaudio":
        return "m4a"
    return media_type_aliases.get(normalized, normalized)

class ConverterInterface:
    supported_input_formats: set = set()  # To be defined by subclasses with supported input formats
    supported_output_formats: set = set()  # To be defined by subclasses with supported output formats
    qualities: set = set()  # Optional quality settings for conversion, can be overridden by subclasses
    formats_with_qualities: set = set()  # Optional set of output formats that have quality options, can be overridden by subclasses
    supports_options: bool = False  # Whether convert() accepts advanced ``options`` (encoding.EncodeOptions)
    encoder_used: Optional[str] = None  # Set by option-aware converters to the encoder that produced the output

    qualities = {
        'low',
        'medium',
        'high',
    }

    def __init__(self, input_file: str, output_dir: str, input_type: str, output_type: str):
        """
        Initialize converter interface.
        
        Args:
            input_file: Path to the input file
            output_dir: Directory where the output file will be saved
            input_type: Format of the input file (e.g., "mp4", "mp3")
            output_type: Format of the output file (e.g., "mp4", "mp3")
        """
        self.input_file = input_file
        self.output_dir = output_dir
        self.requested_input_type = input_type.lower()
        self.requested_output_type = output_type.lower()
        self.input_type = _normalize_converter_media_type(self.requested_input_type)
        self.output_type = _normalize_converter_media_type(self.requested_output_type)
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
    
    def can_convert(self) -> bool:
        """
        Check if conversion between the specified formats is possible.
        
        Returns:
            True if conversion is possible, False otherwise.
        """
        raise NotImplementedError("can_convert method must be implemented by subclasses.")
    
    @classmethod
    def can_register(cls) -> bool:
        """
        Check if the converter can be registered based on required non-pip dependencies.
        Should only be overridden if there is some specific condition that must be met for the converter to be registered.
        e.g. FFMpeg must be installed in order for ffmpeg_convert.py to be registered.
        
        Returns:
            True if the converter can be registered, False otherwise.
        """
        return True
    
    @classmethod
    def get_formats_compatible_with(cls, format_type: str) -> set:
        """
        Get the set of compatible formats for conversion.
        
        Args:
            format_type: The input format to check compatibility for.
        
        Returns:
            Set of compatible formats.
        """
        fmt = media_type_aliases.get(format_type.lower(), format_type.lower())
        return cls.supported_output_formats - {fmt}
    
    @classmethod
    def get_quality_options(cls) -> set:
        """
        Get the set of quality options available for this converter.
        
        Returns:
            Set of quality options.
        """
        return cls.qualities
    
    @classmethod
    def get_formats_with_quality_options(cls) -> set:
        """
        Get the set of output formats that have quality options available.
        
        Returns:
            Set of output formats with quality options.
        """
        return cls.formats_with_qualities
    
    def convert(self, overwrite: bool = True, quality: Optional[str] = None) -> list[str]:
        """
        Convert the input file to the output format.

        Converters with ``supports_options = True`` also accept the keyword
        arguments ``options`` (``encoding.EncodeOptions``), ``progress_cb`` and
        ``cancel_event``. Callers only pass them to such converters.

        Args:
            overwrite: Whether to overwrite existing output file (default: True)
            quality: Quality setting for conversion (e.g., "high", "medium", "low")
        
        Returns:
            List of paths to the converted output files.
        """
        raise NotImplementedError("convert method must be implemented by subclasses.")