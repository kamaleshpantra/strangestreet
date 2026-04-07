from pybloom_live import ScalableBloomFilter
from sqlalchemy.orm import Session
from app.models import User
import logging

logger = logging.getLogger(__name__)

class BloomService:
    def __init__(self):
        # We use ScalableBloomFilter so we don't have to guess the max capacity.
        # It automatically scales by adding internal basic bloom filters as it fills.
        self.username_filter = ScalableBloomFilter(mode=ScalableBloomFilter.SMALL_SET_GROWTH, error_rate=0.01)
        self.email_filter = ScalableBloomFilter(mode=ScalableBloomFilter.SMALL_SET_GROWTH, error_rate=0.01)
        self.alias_filter = ScalableBloomFilter(mode=ScalableBloomFilter.SMALL_SET_GROWTH, error_rate=0.01)
        self.is_initialized = False

    def init_filters(self, db: Session):
        """Seed the bloom filters with all existing usernames, emails, and alias names."""
        if self.is_initialized:
            return

        logger.info("Initializing Bloom Filters for usernames, emails, and aliases...")
        users = db.query(User.username, User.email, User.alias_name).all()
        for u in users:
            if u.username:
                self.username_filter.add(u.username.lower())
            if u.email:
                self.email_filter.add(u.email.lower())
            if u.alias_name:
                self.alias_filter.add(u.alias_name.lower())
        
        self.is_initialized = True
        logger.info(f"Bloom Filters loaded with {len(users)} users.")

    def add_user(self, username: str, email: str, alias_name: str = None):
        """Add a new user's credentials to the filters instantly."""
        if username:
            self.username_filter.add(username.lower())
        if email:
            self.email_filter.add(email.lower())
        if alias_name:
            self.alias_filter.add(alias_name.lower())

    def might_username_exist(self, username: str) -> bool:
        """Returns True if the username might exist. False means it DEFINITELY does NOT exist."""
        return username.lower() in self.username_filter

    def might_email_exist(self, email: str) -> bool:
        """Returns True if the email might exist. False means it DEFINITELY does NOT exist."""
        return email.lower() in self.email_filter

    def might_alias_exist(self, alias_name: str) -> bool:
        """Returns True if the alias_name might exist."""
        return alias_name.lower() in self.alias_filter

# Global singleton instance
bloom_service = BloomService()
