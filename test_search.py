import requests
import json

def test_search():
    # Test data
    sample_request = {
        "id": 123,
        "created_at": "2024-07-22T23:59:45.910559+00:00",
        "transcript": "what is today's weather in california",
        "transcript_segments": [
            {
                "text": "what is today's weather in california",
                "speaker": "SPEAKER_00",
                "is_user": False,
                "start": 0.0,
                "end": 5.0
            }
        ],
        "structured": {
            "category": "science"
        }
    }

    # Your API endpoint
    BASE_URL = "https://h5j41do3vk.execute-api.us-east-1.amazonaws.com/dev"  
    USER_ID = "1"          
    
    # Test endpoints
    def test_setup_completed():
        response = requests.get(f"{BASE_URL}/setup_completed?uid={USER_ID}")
        print("\nSetup Status:")
        print(json.dumps(response.json(), indent=2))
        return response.json()

    def test_search_endpoint():
        response = requests.post(
            f"{BASE_URL}/search?uid={USER_ID}",
            json=sample_request,
            headers={"Content-Type": "application/json"}
        )
        print("\nSearch Results:")
        print(json.dumps(response.json(), indent=2))
        return response.json()

    # Run tests
    setup_status = test_setup_completed()
    if setup_status.get("is_setup_completed"):
        search_results = test_search_endpoint()
    else:
        print("Setup not completed. Please set up Google API key first.")

if __name__ == "__main__":
    test_search() 