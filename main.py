from flask import Flask, request, jsonify
from googlesearch import search
import re
from typing import List, Dict
from datetime import datetime

app = Flask(__name__)

class GoogleSearcher:
    def extract_question(self, transcript: str) -> str:
        """Extract the question from the transcript"""
        # Simple pattern matching for questions
        questions = re.findall(r'[^.!?]*\?', transcript)
        return questions[-1].strip() if questions else transcript

    def search_google(self, query: str, num_results: int = 5) -> List[Dict]:
        """Perform Google search and return results"""
        try:
            search_results = []
            for result in search(query, num_results=num_results):
                search_results.append({
                    "url": result,
                    "timestamp": datetime.now().isoformat()
                })
            return search_results
        except Exception as e:
            print(f"Search error: {str(e)}")
            return []

@app.route('/webhook', methods=['POST'])
def memory_webhook():
    # Get the user ID from query parameters
    user_id = request.args.get('uid')
    if not user_id:
        return jsonify({"error": "No user ID provided"}), 400

    try:
        # Parse the incoming memory data
        memory_data = request.json
        
        # Extract transcript
        transcript = memory_data.get('transcript', '')
        
        # Initialize searcher
        searcher = GoogleSearcher()
        
        # Extract question and perform search
        question = searcher.extract_question(transcript)
        search_results = searcher.search_google(question)
        
        # Prepare the response
        response = {
            "app_id": "google-search-assistant",
            "content": {
                "question": question,
                "search_results": search_results,
                "timestamp": datetime.now().isoformat()
            }
        }
        
        return jsonify(response), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/setup-status', methods=['GET'])
def setup_status():
    return jsonify({"is_setup_completed": True})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
