#!/usr/bin/env python3
"""
Yad2 Car Monitor - Optimized for Israeli car marketplace
Monitors total results counter for efficient new car detection
"""

import os
import sys
import json
import requests
import time
import re
from datetime import datetime
from typing import Dict, List, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class Yad2CarMonitor:
    def __init__(self, config: Dict):
        self.url = config['url']
        self.telegram_bot_token = config['telegram_bot_token']
        self.telegram_chat_id = config['telegram_chat_id']
        self.storage_file = config.get('storage_file', 'yad2_data.json')
        self.driver = None
        self.data = self.load_data()
        
    def load_data(self) -> Dict:
        """Load previous monitoring data"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading data: {e}")
        
        return {
            'last_total': 0,
            'last_check': None,
            'history': [],
            'seen_car_ids': []
        }
    
    def save_data(self):
        """Save monitoring data"""
        try:
            self.data['last_check'] = datetime.now().isoformat()
            with open(self.storage_file, 'w') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving data: {e}")
    
    def setup_driver(self):
        """Setup Selenium driver for GitHub Actions"""
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--lang=he-IL')  # Hebrew locale for Yad2
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        # Disable images for faster loading
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(10)
    
    def close_driver(self):
        """Clean up driver"""
        if self.driver:
            self.driver.quit()
            self.driver = None
    
    def get_total_results(self) -> Optional[int]:
        """Extract total results count from Yad2"""
        try:
            print(f"Loading Yad2: {self.url}")
            self.driver.get(self.url)
            
            # Wait for page to load - try multiple selectors
            wait = WebDriverWait(self.driver, 20)
            
            # Selectors for total results counter (in order of preference)
            total_selectors = [
                "span[data-testid='total-items']",
                "span[class*='totalItems']",
                "span.results-feed_sortAndTotalBox__lFFyS",  
                "span[class*='sortAndTotalBox']",
                "span[class*='totalResults']",
                "div[class*='totalBox'] span",
                "//span[contains(text(),'נמצאו')]",  
                "//span[contains(text(),'מודעות')]",  
            ]
            
            total_text = None
            for selector in total_selectors:
                try:
                    if selector.startswith('//'):
                        # XPath selector
                        element = wait.until(EC.presence_of_element_located((By.XPATH, selector)))
                    else:
                        # CSS selector
                        element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    
                    total_text = element.text
                    print(f"Found total text: {total_text}")
                    break
                except:
                    continue
            
            if not total_text:
                # Try getting any text that looks like a results counter
                possible_elements = self.driver.find_elements(By.XPATH, "//span[contains(text(),'נמצאו') or contains(text(),'מודעות')]")
                for elem in possible_elements:
                    text = elem.text
                    if any(char.isdigit() for char in text):
                        total_text = text
                        print(f"Found alternative total text: {total_text}")
                        break
            
            if total_text:
                # Extract number from text (works with Hebrew)
                # Examples: "נמצאו 123 מודעות", "123 results", "סה״כ: 123"
                numbers = re.findall(r'\d+', total_text)
                if numbers:
                    # Take the first number (usually the total)
                    total = int(numbers[0])
                    print(f"Extracted total: {total}")
                    return total
            
            # Fallback 1: search any visible element containing Hebrew keywords and digits
            print("Fallback: searching page elements for candidate texts containing 'תוצאות', 'מודעות' or 'נמצאו'")
            try:
                candidates = self.driver.find_elements(By.XPATH, "//*[contains(text(),'תוצאות') or contains(text(),'מודעות') or contains(text(),'נמצאו') or contains(text(),'תוצאה')]")
                for elem in candidates:
                    text = elem.text.strip()
                    if not text:
                        continue
                    print(f"Candidate element text: {text}")
                    nums = re.findall(r'\d+', text)
                    if nums:
                        total = int(nums[0])
                        print(f"Extracted total from candidate: {total}")
                        return total
            except Exception:
                pass

            # Fallback 2: search page source for the pattern '123 תוצאות' or '123 מודעות'
            print("Fallback: searching page source for numeric counter patterns")
            try:
                src = self.driver.page_source
                m = re.search(r"(\d{1,6})\s*(תוצאות|מודעות|נמצאו|תוצאה)", src)
                if m:
                    total = int(m.group(1))
                    print(f"Extracted total from page source: {total}")
                    return total
            except Exception:
                pass

            print("Warning: Could not find total results counter")
            return None
            
        except Exception as e:
            print(f"Error getting total results: {e}")
            return None
    
    def get_new_listings(self) -> List[Dict]:
        """Get details of new listings (first few)"""
        new_listings = []
        
        try:
            # Wait for listings to load
            wait = WebDriverWait(self.driver, 10)
            
            # Selectors for individual car listings on Yad2
            listing_selectors = [
                "div[data-testid='feed-item']",
                "div.feed-item_feedItem__Hn7A7",
                "div[class*='feedItem']",
                "article[class*='item']",
                "div.ad-container"
            ]
            
            listings = []
            for selector in listing_selectors:
                listings = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if listings:
                    print(f"Found {len(listings)} listings with selector: {selector}")
                    break
            
            # Get first 5 listings for new car details
            for listing in listings[:5]:
                try:
                    car_info = {}
                    
                    # Try to get title/model
                    title_selectors = ["h3", "h4", "[class*='title']", "a[class*='title']"]
                    for sel in title_selectors:
                        try:
                            title = listing.find_element(By.CSS_SELECTOR, sel).text
                            if title:
                                car_info['title'] = title
                                break
                        except:
                            continue
                    
                    # Try to get price
                    price_selectors = ["[class*='price']", "span[class*='price']", "[data-testid*='price']"]
                    for sel in price_selectors:
                        try:
                            price = listing.find_element(By.CSS_SELECTOR, sel).text
                            if price and ('₪' in price or any(char.isdigit() for char in price)):
                                car_info['price'] = price
                                break
                        except:
                            continue
                    
                    # Try to get link
                    try:
                        link = listing.find_element(By.TAG_NAME, "a").get_attribute("href")
                        if link:
                            car_info['link'] = link
                    except:
                        pass
                    
                    # Get any additional details
                    text = listing.text[:300]  # First 300 chars
                    car_info['details'] = text
                    
                    if car_info:
                        new_listings.append(car_info)
                        
                except Exception as e:
                    print(f"Error extracting listing details: {e}")
                    continue
            
        except Exception as e:
            print(f"Error getting new listings: {e}")
        
        return new_listings
    
    def send_telegram_message(self, message: str) -> bool:
        """Send Telegram notification"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': False
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            print("Telegram notification sent")
            return True
            
        except Exception as e:
            print(f"Error sending Telegram: {e}")
            return False
    
    def format_notification(self, old_total: int, new_total: int, new_listings: List[Dict]) -> str:
        """Format notification message"""
        diff = new_total - old_total
        
        if diff > 0:
            message = f"🚗 <b>רכבים חדשים ביד2!</b>\n\n"
            message += f"📊 סה״כ עכשיו: {new_total} ({diff:+d} חדשים)\n"
        else:
            message = f"📉 <b>שינוי במספר הרכבים</b>\n\n"
            message += f"📊 סה״כ עכשיו: {new_total} ({diff:+d})\n"
        
        message += f"🔗 <a href=\"{self.url}\">לצפייה בכל המודעות</a>\n"
        
        # Add details of new listings if available
        if new_listings and diff > 0:
            message += "\n<b>רכבים חדשים:</b>\n"
            for i, car in enumerate(new_listings[:3], 1):
                if car.get('title'):
                    message += f"\n{i}. {car['title']}"
                if car.get('price'):
                    message += f"\n   💰 {car['price']}"
                if car.get('link'):
                    message += f"\n   🔗 <a href=\"{car['link']}\">צפה במודעה</a>"
                message += "\n"
        
        message += f"\n⏰ {datetime.now().strftime('%H:%M - %d/%m/%Y')}"
        
        return message
    
    def run(self):
        """Main monitoring logic"""
        print(f"=== Yad2 Monitor Started ===")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"URL: {self.url}")
        print(f"Last total: {self.data['last_total']}")
        
        try:
            self.setup_driver()
            
            # Get current total
            current_total = self.get_total_results()
            
            if current_total is None:
                print("Could not get total results count")
                self.send_telegram_message(
                    "⚠️ <b>בעיה בניטור יד2</b>\n\n"
                    "לא הצלחתי לקרוא את מספר המודעות.\n"
                    "הניטור ימשיך בבדיקה הבאה.\n\n"
                    f"🔗 <a href=\"{self.url}\">בדוק ידנית</a>"
                )
                return
            
            print(f"Current total: {current_total}")
            
            # First run - initialize
            if self.data['last_total'] == 0:
                print("First run - initializing")
                self.data['last_total'] = current_total
                self.data['history'].append({
                    'timestamp': datetime.now().isoformat(),
                    'total': current_total
                })
                self.save_data()
                
                self.send_telegram_message(
                    f"✅ <b>ניטור יד2 הופעל!</b>\n\n"
                    f"📊 סה״כ רכבים כרגע: {current_total}\n"
                    f"⏱️ בודק כל 20 דקות (06:00-00:00)\n"
                    f"🔗 <a href=\"{self.url}\">קישור לחיפוש</a>\n\n"
                    f"תקבל התראה כשיתווספו רכבים חדשים! 🚗"
                )
                return
            
            # Check for changes
            diff = current_total - self.data['last_total']
            
            if diff != 0:
                print(f"Change detected: {diff:+d}")
                
                # Get new listings details if count increased
                new_listings = []
                if diff > 0:
                    new_listings = self.get_new_listings()
                
                # Send notification
                message = self.format_notification(
                    self.data['last_total'],
                    current_total,
                    new_listings
                )
                self.send_telegram_message(message)
                
                # Update data
                self.data['last_total'] = current_total
                self.data['history'].append({
                    'timestamp': datetime.now().isoformat(),
                    'total': current_total,
                    'change': diff
                })
                
                # Keep only last 100 history entries
                if len(self.data['history']) > 100:
                    self.data['history'] = self.data['history'][-100:]
                
                self.save_data()
            else:
                print("No change in total listings")
                
                # Send periodic status update (every 50 checks)
                check_count = len(self.data.get('history', []))
                if check_count % 50 == 0 and check_count > 0:
                    self.send_telegram_message(
                        f"📊 <b>סטטוס ניטור יד2</b>\n\n"
                        f"✅ המערכת פעילה\n"
                        f"📈 סה״כ רכבים: {current_total}\n"
                        f"🔄 בדיקות שבוצעו: {check_count}\n"
                        f"⏰ בדיקה אחרונה: {datetime.now().strftime('%H:%M')}"
                    )
            
        except Exception as e:
            print(f"Error in monitoring: {e}")
            self.send_telegram_message(
                f"❌ <b>שגיאה בניטור</b>\n\n"
                f"Error: {str(e)[:200]}\n\n"
                f"הניטור ימשיך בבדיקה הבאה."
            )
        finally:
            self.close_driver()
            print("=== Monitor Completed ===")

def main():
    """Main entry point"""
    config = {
        'url': os.environ.get('CAR_LISTING_URL'),
        'telegram_bot_token': os.environ.get('TELEGRAM_BOT_TOKEN'),
        'telegram_chat_id': os.environ.get('TELEGRAM_CHAT_ID'),
        'storage_file': os.environ.get('STORAGE_FILE', 'yad2_data.json')
    }
    
    # Validate
    if not all([config['url'], config['telegram_bot_token'], config['telegram_chat_id']]):
        print("Error: Missing required environment variables")
        sys.exit(1)
    
    # Check if URL is Yad2
    if 'yad2.co.il' not in config['url']:
        print("Warning: This scraper is optimized for Yad2.co.il")
    
    monitor = Yad2CarMonitor(config)
    monitor.run()

if __name__ == "__main__":
    main()
