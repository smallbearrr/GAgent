import os
import sys

# Add project root to sys.path so we can import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../")))

from app.services.interpretation.data_process import DataProcessor

def test_mat_metadata():
    # Adjust this filename if necessary
    target_filename = "E-MTAB-8414_cndm.mat"
    
    file_path = os.path.join(os.path.dirname(__file__), "../data", target_filename)
    
    print(f"Testing metadata extraction for: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    try:
        # Extract metadata
        metadata = DataProcessor.get_metadata(file_path)
        
        # Print results
        print("\nMetadata Result:")
        # model_dump_json is available in Pydantic V2
        print(metadata.model_dump_json(indent=2))

        print(metadata)
        
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_mat_metadata()
