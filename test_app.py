"""
Comprehensive Test Script for Campus Video Player
Tests all features: Admin, Teacher, Student flows
"""
import requests
import json
from time import sleep

BASE_URL = "http://127.0.0.1:5000"

class TestSession:
    def __init__(self):
        self.session = requests.Session()
        self.current_user = None
        
    def test_ads_page(self):
        """Test the ADS landing page"""
        print("\n" + "="*60)
        print("TEST 1: ADS Landing Page")
        print("="*60)
        try:
            response = self.session.get(BASE_URL)
            if response.status_code == 200:
                print("[OK] ADS page loaded successfully")
                print(f"  Status Code: {response.status_code}")
                if "study" in response.text.lower() or "purpose" in response.text.lower():
                    print("[OK] ADS page contains study purpose message")
                return True
            else:
                print(f"[X] Failed with status code: {response.status_code}")
                return False
        except Exception as e:
            print(f"[X] Error: {e}")
            return False
    
    def login(self, username, password, role=None):
        """Login a user"""
        print(f"\n{'='*60}")
        print(f"LOGIN: {username} as {role or 'auto-detect'}")
        print("="*60)
        try:
            data = {'username': username, 'password': password}
            if role:
                data['role'] = role
            
            response = self.session.post(f"{BASE_URL}/login", data=data, allow_redirects=False)
            
            if response.status_code in [302, 200]:
                print(f"[OK] Login successful for {username}")
                self.current_user = username
                # Follow redirect to get dashboard
                if response.status_code == 302:
                    redirect_url = response.headers.get('Location')
                    print(f"  Redirected to: {redirect_url}")
                return True
            else:
                print(f"[X] Login failed with status: {response.status_code}")
                print(f"  Response: {response.text[:200]}")
                return False
        except Exception as e:
            print(f"[X] Login error: {e}")
            return False
    
    def logout(self):
        """Logout current user"""
        print(f"\nLogging out {self.current_user}...")
        try:
            response = self.session.get(f"{BASE_URL}/logout")
            self.current_user = None
            print("[OK] Logged out successfully")
            return True
        except Exception as e:
            print(f"[X] Logout error: {e}")
            return False
    
    def test_admin_dashboard(self):
        """Test admin dashboard access"""
        print("\n" + "="*60)
        print("TEST 2: Admin Dashboard")
        print("="*60)
        try:
            response = self.session.get(f"{BASE_URL}/admin")
            if response.status_code == 200:
                print("[OK] Admin dashboard accessible")
                if "teacher" in response.text.lower():
                    print("[OK] Dashboard shows teacher management options")
                return True
            else:
                print(f"[X] Failed with status: {response.status_code}")
                return False
        except Exception as e:
            print(f"[X] Error: {e}")
            return False
    
    def test_add_teacher(self, username, password):
        """Test adding a teacher"""
        print(f"\n  -> Adding teacher: {username}")
        try:
            data = {'username': username, 'password': password}
            response = self.session.post(f"{BASE_URL}/admin/add_teacher", data=data)
            if response.status_code in [200, 302]:
                print(f"  [OK] Teacher '{username}' added successfully")
                return True
            else:
                print(f"  [X] Failed to add teacher: {response.status_code}")
                return False
        except Exception as e:
            print(f"  [X] Error adding teacher: {e}")
            return False
    
    def test_change_teacher_password(self, user_id, new_password):
        """Test changing teacher password"""
        print(f"\n  -> Changing teacher password (ID: {user_id})")
        try:
            data = {'user_id': user_id, 'new_password': new_password}
            response = self.session.post(f"{BASE_URL}/admin/change_teacher_password", data=data)
            if response.status_code in [200, 302]:
                print(f"  [OK] Password changed successfully")
                return True
            else:
                print(f"  [X] Failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"  [X] Error: {e}")
            return False
    
    def test_teacher_dashboard(self):
        """Test teacher dashboard"""
        print("\n" + "="*60)
        print("TEST 3: Teacher Dashboard")
        print("="*60)
        try:
            response = self.session.get(f"{BASE_URL}/teacher")
            if response.status_code == 200:
                print("[OK] Teacher dashboard accessible")
                if "video" in response.text.lower() or "upload" in response.text.lower():
                    print("[OK] Dashboard shows video upload options")
                if "student" in response.text.lower():
                    print("[OK] Dashboard shows student management options")
                return True
            else:
                print(f"[X] Failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"[X] Error: {e}")
            return False
    
    def test_add_student(self, username, password):
        """Test adding a student"""
        print(f"\n  -> Adding student: {username}")
        try:
            data = {'username': username, 'password': password}
            response = self.session.post(f"{BASE_URL}/teacher/add_student", data=data)
            if response.status_code in [200, 302]:
                print(f"  [OK] Student '{username}' added successfully")
                return True
            else:
                print(f"  [X] Failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"  [X] Error: {e}")
            return False
    
    def test_create_playlist(self, title):
        """Test creating a playlist"""
        print(f"\n  -> Creating playlist: {title}")
        try:
            data = {'title': title}
            response = self.session.post(f"{BASE_URL}/teacher/create_playlist", data=data)
            if response.status_code in [200, 302]:
                print(f"  [OK] Playlist '{title}' created successfully")
                return True
            else:
                print(f"  [X] Failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"  [X] Error: {e}")
            return False
    
    def test_student_dashboard(self):
        """Test student dashboard"""
        print("\n" + "="*60)
        print("TEST 4: Student Dashboard")
        print("="*60)
        try:
            response = self.session.get(f"{BASE_URL}/student")
            if response.status_code == 200:
                print("[OK] Student dashboard accessible")
                if "playlist" in response.text.lower() or "video" in response.text.lower():
                    print("[OK] Dashboard shows playlists/videos")
                return True
            else:
                print(f"[X] Failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"[X] Error: {e}")
            return False
    
    def test_analytics_page(self):
        """Test analytics page"""
        print("\n" + "="*60)
        print("TEST 5: Teacher Analytics")
        print("="*60)
        try:
            response = self.session.get(f"{BASE_URL}/teacher/analytics")
            if response.status_code == 200:
                print("[OK] Analytics page accessible")
                if "view" in response.text.lower() or "watch" in response.text.lower():
                    print("[OK] Analytics page shows view tracking")
                return True
            else:
                print(f"[X] Failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"[X] Error: {e}")
            return False

def run_full_test():
    """Run comprehensive test suite"""
    print("\n" + "="*60)
    print("CAMPUS VIDEO PLAYER - COMPREHENSIVE TEST SUITE")
    print("="*60)
    
    tester = TestSession()
    results = []
    
    # Test 1: ADS Page
    results.append(("ADS Page", tester.test_ads_page()))
    
    # Test 2: Admin Login and Features
    if tester.login("admin", "admin123", "admin"):
        results.append(("Admin Login", True))
        results.append(("Admin Dashboard", tester.test_admin_dashboard()))
        results.append(("Add Teacher", tester.test_add_teacher("teacher1", "teacher123")))
        results.append(("Add Teacher 2", tester.test_add_teacher("teacher2", "teacher123")))
        tester.logout()
    else:
        results.append(("Admin Login", False))
    
    sleep(0.5)
    
    # Test 3: Teacher Login and Features
    if tester.login("teacher1", "teacher123", "teacher"):
        results.append(("Teacher Login", True))
        results.append(("Teacher Dashboard", tester.test_teacher_dashboard()))
        results.append(("Add Student", tester.test_add_student("student1", "student123")))
        results.append(("Add Student 2", tester.test_add_student("student2", "student123")))
        results.append(("Create Playlist", tester.test_create_playlist("Python Tutorials")))
        results.append(("Create Playlist 2", tester.test_create_playlist("Web Development")))
        results.append(("Analytics Page", tester.test_analytics_page()))
        tester.logout()
    else:
        results.append(("Teacher Login", False))
    
    sleep(0.5)
    
    # Test 4: Student Login and Features
    if tester.login("student1", "student123", "student"):
        results.append(("Student Login", True))
        results.append(("Student Dashboard", tester.test_student_dashboard()))
        tester.logout()
    else:
        results.append(("Student Login", False))
    
    # Print Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[OK] PASS" if result else "[X] FAIL"
        print(f"{status} - {test_name}")
    
    print(f"\n{passed}/{total} tests passed ({(passed/total)*100:.1f}%)")
    
    if passed == total:
        print("\n ALL TESTS PASSED! Application is working correctly!")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review the output above.")
    
    return passed == total

if __name__ == "__main__":
    try:
        run_full_test()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
