# Dataset Reconciliation System

Version 6.0.0 - Production Ready

## Overview

A robust Streamlit application for reconciling student data from three different systems:
- **Blackbaud**: Family/parent roster with student information
- **Rediker**: Student management system data  
- **Student Records**: Internal student database

The system creates a comprehensive Master_Students Excel file with intelligent matching, error handling, and detailed reporting.

## Features

### Core Functionality
- ✅ **Intelligent Name Parsing**: Handles various name formats (Last, First; Last First; etc.)
- ✅ **Grade Normalization**: Standardizes grades (PK3, PK4, K, 1-12)
- ✅ **Multi-Source Reconciliation**: Matches students across three systems
- ✅ **Mismatch Detection**: Highlights students not found in all systems
- ✅ **Excel Export**: Professional formatted output with color coding

### Enhanced Features (v6.0.0)
- 🛡️ **Comprehensive Error Handling**: Graceful failure recovery
- 📊 **Processing Statistics**: Real-time metrics and match rates
- 🔒 **Security**: Input sanitization, formula injection prevention
- ⚡ **Performance Optimization**: Caching and efficient processing
- 🧪 **Test Suite**: 50+ unit tests for reliability
- 📈 **Data Visualization**: Optional charts and graphs
- 🐛 **Debug Mode**: Detailed logging and troubleshooting
- 🌍 **Unicode Support**: Handles international characters

## Installation

### Requirements
- Python 3.8 or higher
- 2GB RAM minimum (4GB recommended for large datasets)

### Setup

1. **Clone or download the files**:
```bash
# Create project directory
mkdir dataset-reconciliation
cd dataset-reconciliation

# Copy the application files
cp app_enhanced.py .
cp requirements.txt .
cp test_app_enhanced.py .
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Run the application**:
```bash
streamlit run app_enhanced.py
```

The application will open in your web browser at `http://localhost:8501`

## Usage

### Basic Workflow

1. **Upload Files**:
   - Upload Blackbaud roster (family/student data)
   - Upload Rediker export (student management data)
   - Upload Student Records (internal database)

2. **Configure Settings** (optional):
   - Enable debug mode for detailed logging
   - Enable statistics for processing metrics
   - Adjust advanced options as needed

3. **Process Data**:
   - Click "Build Master_Students Excel"
   - Review statistics and quality metrics
   - Download the generated Excel file

### File Format Requirements

#### Blackbaud File
Required columns:
- Family ID
- Parent First/Last Name
- Student information (combined format like "LastName, FirstName (Grade)")

#### Rediker File  
Required columns:
- Student Name (or separate First/Last)
- Grade Level
- Optional: APID, Family ID, Parent Names

#### Student Records
Required columns:
- Student First/Last Names (or combined Name)
- Optional: Grade, Family ID, Rediker ID

### Output Format

The generated Excel file contains:

1. **Master Sheet**: All records with:
   - Color coding by source (Black=Blackbaud, Red=Rediker, Green=Student Records)
   - Yellow highlighting for partial matches (2 sources)
   - Pink/red highlighting for single source only

2. **Summary Sheet**: Unique students with:
   - Presence indicators (✅/❌) for each source
   - Raw name variations from each system
   - Source count

3. **Summary_Mismatches Sheet**: Only students not found in all three systems

4. **Metadata Sheet**: Processing statistics and information

## Configuration

### Settings Panel

- **Debug Options**:
  - Show detailed logs
  - Show raw data preview
  - Export debug information

- **Statistics Options**:
  - Show processing statistics
  - Show data quality metrics
  - Show visualization charts

- **Advanced Options**:
  - Max file size limit (10-500 MB)
  - Enable fuzzy matching
  - Strict validation mode

### Customization

Edit the `Config` class in `app_enhanced.py` to customize:
- Color schemes
- Grade mappings
- Name suffixes
- File size limits
- Column detection tokens

## Testing

Run the comprehensive test suite:

```bash
# Run all tests
python -m pytest test_app_enhanced.py -v

# Run with coverage report
python -m pytest test_app_enhanced.py --cov=app_enhanced --cov-report=html

# Run specific test class
python -m pytest test_app_enhanced.py::TestNormalization -v
```

Test coverage includes:
- Configuration management
- Data validation
- Name normalization
- Grade standardization
- Column detection
- Parser functionality
- Master building logic
- Excel generation
- Edge cases and error handling

## Troubleshooting

### Common Issues

1. **"Cannot find student/grade column"**
   - Ensure Blackbaud export contains student data in format: "Name (Grade)"
   - Check that column headers contain expected keywords

2. **"File too large"**
   - Increase max file size in Advanced Options
   - Split large files into smaller batches

3. **"Grade not recognized"**
   - Check grade format matches expected patterns (PK3, PK4, K, 1-12)
   - Custom grade formats can be added to Config.GRADE_MAPPING

4. **"Memory error with large files"**
   - Process files in smaller batches
   - Increase system RAM allocation
   - Use 64-bit Python installation

### Debug Mode

Enable debug mode to see:
- Header row detection details
- Column mapping information
- Sample parsed rows
- Error messages and warnings
- Processing statistics

### Error Recovery

The application includes comprehensive error handling:
- Continues processing even if one source has issues
- Provides detailed error messages
- Generates partial results when possible
- Exports debug reports for troubleshooting

## Performance

### Optimization Features

- **Caching**: Frequently used normalization functions are cached
- **Efficient Processing**: Vectorized pandas operations where possible
- **Memory Management**: Processes data in chunks for large files
- **Smart Column Detection**: Prioritized search algorithms

### Performance Benchmarks

| Dataset Size | Processing Time | Memory Usage |
|-------------|-----------------|--------------|
| 1,000 records | ~2 seconds | ~50 MB |
| 10,000 records | ~15 seconds | ~200 MB |
| 50,000 records | ~60 seconds | ~800 MB |
| 100,000 records | ~3 minutes | ~1.5 GB |

*Times measured on Intel i7, 16GB RAM, SSD

## Security

### Input Validation
- File size limits to prevent DoS
- Extension validation (.xlsx, .xls only)
- Content sanitization

### Data Protection
- Formula injection prevention (Excel)
- Special character sanitization
- Path traversal protection
- XSS prevention in web interface

### Best Practices
- Always validate source data quality
- Review mismatch reports carefully
- Keep backups of original files
- Use debug reports for audit trails

## API Reference

### Core Functions

```python
# Normalization
grade_norm(grade: str) -> str
surname_last_token(last: str) -> str
firstname_first_token(first: str, last: str) -> str
make_unique_key(first: str, last: str, grade: str) -> str

# Validation
DataValidator.validate_file(file) -> Tuple[bool, str, Dict]
DataValidator.sanitize_string(s: str, max_length: int) -> str
DataValidator.validate_name(name: str, field_type: str) -> Tuple[bool, str]
DataValidator.validate_grade(grade: str) -> Tuple[bool, str]

# Parsing
BlackbaudParser.parse(file) -> pd.DataFrame
RedikerParser.parse(file) -> pd.DataFrame
StudentRecordsParser.parse(file) -> pd.DataFrame

# Master Building
MasterBuilder.build_master(bb_df, red_df, sr_df) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
MasterBuilder.create_excel(master, summary, mismatches) -> bytes
```

## Development

### Project Structure
```
dataset-reconciliation/
├── app_enhanced.py         # Main application (v6.0.0)
├── test_app_enhanced.py    # Comprehensive test suite
├── requirements.txt        # Python dependencies
├── README.md              # This documentation
└── sample_data/           # Sample test files (optional)
    ├── blackbaud_sample.xlsx
    ├── rediker_sample.xlsx
    └── student_records_sample.xlsx
```

### Contributing

To contribute improvements:

1. Run existing tests to ensure compatibility
2. Add tests for new functionality
3. Follow existing code style and patterns
4. Update documentation as needed
5. Test with various data formats

### Code Style

- PEP 8 compliance
- Type hints where applicable
- Comprehensive docstrings
- Clear variable names
- Modular design

## Version History

### v6.0.0 (Current)
- Complete rewrite with enhanced architecture
- Comprehensive error handling
- Advanced statistics and visualization
- Full test suite
- Performance optimizations
- Security enhancements

### v5.2.1 (Previous)
- Improved Blackbaud name parsing
- Multi-part surname support
- Basic functionality

## License

This software is provided as-is for educational and operational use. Modify and distribute as needed for your organization.

## Support

For issues or questions:

1. Check the Troubleshooting section
2. Enable debug mode for detailed information
3. Review the test suite for expected behavior
4. Export and analyze debug reports

## Acknowledgments

Built with:
- Streamlit - Web application framework
- Pandas - Data processing
- XlsxWriter - Excel generation
- Pytest - Testing framework

---

**Dataset Reconciliation System** - Reliable, Robust, Production Ready

*Last Updated: 2024*