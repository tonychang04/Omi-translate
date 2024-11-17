'''
class TranslationBuffer:
    def __init__(self):
        self.buffers = {}
        self.lock = threading.Lock()
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()
        self.TRIGGER_WORDS = ["translate", "translate to", "translate this"]
        self.NOTIFICATION_COOLDOWN = 10
        self.QUESTION_AGGREGATION_TIME = 5

    def cleanup_old_sessions(self):
        """Clean up old sessions from the buffer"""
        try:
            current_time = time.time()
            with self.lock:
                # Find sessions older than 1 hour
                expired_sessions = [
                    session_id for session_id, data in self.buffers.items()
                    if current_time - data.get('last_activity', 0) > 3600
                ]
                
                # Remove expired sessions
                for session_id in expired_sessions:
                    logger.info(f"[CLEANUP] Removing expired session: {session_id}")
                    del self.buffers[session_id]
                
                # Update last cleanup time
                self.last_cleanup = current_time
                
                logger.info(f"[CLEANUP] Removed {len(expired_sessions)} expired sessions")
                
        except Exception as e:
            logger.error(f"[CLEANUP] Error during cleanup: {str(e)}")
            # Don't raise the error - cleanup failure shouldn't break the main flow

    def get_buffer(self, session_id):
        """Get or create a buffer for a session"""
        current_time = time.time()
        
        # Run cleanup if needed
        if current_time - self.last_cleanup > self.cleanup_interval:
            logger.info("[CLEANUP] Starting scheduled cleanup")
            self.cleanup_old_sessions()
        
        with self.lock:
            # Create new buffer if needed
            if session_id not in self.buffers:
                logger.info(f"[BUFFER] Creating new buffer for session {session_id}")
                self.buffers[session_id] = {
                    'messages': [],
                    'trigger_detected': False,
                    'trigger_time': 0,
                    'collected_text': [],
                    'response_sent': False,
                    'last_activity': current_time
                }
            else:
                # Update last activity time
                self.buffers[session_id]['last_activity'] = current_time
                logger.info(f"[BUFFER] Updated last activity for session {session_id}")
                
        return self.buffers[session_id]

# Initialize the translation buffer instance
translation_buffer = TranslationBuffer()
'''