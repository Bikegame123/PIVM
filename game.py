import pygame
import random
import sys
import math
from perlin_noise import PerlinNoise
import datetime # NEW: For timestamp
import firebase_admin 
from firebase_admin import credentials, firestore

# --- WII BOARD INTEGRATION START ---
# Make sure you have installed evdev: sudo apt install python3-evdev
import threading
from evdev import InputDevice, categorize, ecodes, list_devices
# --- WII BOARD INTEGRATION END ---


# --- FIREBASE INTEGRATION START ---
# IMPORTANT: Replace 'path/to/your/serviceAccountKey.json' 
# with the actual path to the JSON file you downloaded and secured.
SERVICE_ACCOUNT_KEY_PATH = "path/to/your/serviceAccountKey.json"

# Global Firestore client variable
db = None

try:
    # Initialize Firebase Admin SDK
    # Ensure this runs only once
    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase initialized successfully.")
except Exception as e:
    print(f"!! FIREBASE ERROR: Could not initialize Firebase. Check path and keys. Error: {e}")
    # db remains None if initialization fails
# --- FIREBASE INTEGRATION END ---


# Initialize Pygame
pygame.init()
pygame.mixer.init()

# Load sounds
try:
    dead_sound = pygame.mixer.Sound("dead.wav")
    pygame.mixer.music.load("music loop.wav")
    print("Sounds loaded successfully")
except pygame.error as e:
    print(f"Sound files not found: {e}")
    dead_sound = None

# --- Constants ---
# NEW: Renamed to reflect the "design" resolution
DESIGN_WIDTH = 800
DESIGN_HEIGHT = 600
FPS = 60
PLAYER_SPEED = 5
OBSTACLE_SPEED = 3
POWERUP_SPEED = 3
NEON_BLUE = (0, 255, 255)
NEON_PINK = (255, 0, 255)
NEON_GREEN = (0, 255, 0)
BLACK = (10, 10, 10)
WHITE = (255, 255, 255)
ORANGE = (255, 165, 0)
RED = (255, 0, 0)
GOLD = (255, 215, 0)
PURPLE = (180, 0, 255)
GREY = (150, 150, 150)

# --- NEW: Fullscreen and Scaling Setup ---
# Get the native resolution of the monitor
try:
    info = pygame.display.Info()
    FINAL_SCREEN_WIDTH = info.current_w
    FINAL_SCREEN_HEIGHT = info.current_h
except pygame.error:
    # Fallback if display info is not available (e.g., no display server)
    print("Could not get display info. Defaulting to 1920x1080.")
    FINAL_SCREEN_WIDTH = 1920
    FINAL_SCREEN_HEIGHT = 1080


# Set up the *final* display in FULLSCREEN
display_surface = pygame.display.set_mode((FINAL_SCREEN_WIDTH, FINAL_SCREEN_HEIGHT), pygame.FULLSCREEN)

# Create the "virtual" screen (a Surface) that the game will draw on
# All existing game logic is based on this 800x600 size
screen = pygame.Surface((DESIGN_WIDTH, DESIGN_HEIGHT))

pygame.display.set_caption("Neon Runner")
clock = pygame.time.Clock()

# NEW: Calculate scaling factors to fit 800x600 into the final resolution
# This preserves the aspect ratio (letterboxing)
scale_ratio = min(FINAL_SCREEN_WIDTH / DESIGN_WIDTH, FINAL_SCREEN_HEIGHT / DESIGN_HEIGHT)
scaled_width = int(DESIGN_WIDTH * scale_ratio)
scaled_height = int(DESIGN_HEIGHT * scale_ratio)

# Calculate the top-left position to blit the scaled surface so it's centered
blit_x = (FINAL_SCREEN_WIDTH - scaled_width) // 2
blit_y = (FINAL_SCREEN_HEIGHT - scaled_height) // 2
# --- End of Scaling Setup ---


# --- NEW: Display Helper Function ---
def update_display():
    """
    Takes the 800x600 'screen' surface, scales it up,
    and blits it onto the *real* fullscreen display.
    """
    # Fill the letterbox/pillarbox areas with black
    display_surface.fill(BLACK)
    
    # Scale the 800x600 virtual screen to the new calculated size
    # Using smoothscale for better quality than transform.scale
    scaled_surface = pygame.transform.smoothscale(screen, (scaled_width, scaled_height))
    
    # Blit the scaled surface onto the center of the real display
    display_surface.blit(scaled_surface, (blit_x, blit_y))
    
    # Update the real display
    pygame.display.flip()
# -----------------------------------


# --- Load Custom Font ---
try:
    font = pygame.font.Font("PressStart2P-Regular.ttf", 20)
    big_font = pygame.font.Font("PressStart2P-Regular.ttf", 40)
    small_font = pygame.font.Font("PressStart2P-Regular.ttf", 14)
except pygame.error:
    print("Font file 'PressStart2P-Regular.ttf' not found! Falling back to default.")
    font = pygame.font.SysFont("monospace", 30)
    big_font = pygame.font.SysFont("monospace", 60)
    small_font = pygame.font.SysFont("monospace", 18)

# Cybersecurity questions
questions = [
    {"question": "What does 'phishing' mean?", "options": ["A scam to steal personal info", "A type of fish", "A network protocol"], "correct": 0},
    {"question": "What is a firewall?", "options": ["Blocks unauthorized access", "A wall that prevents fires", "A type of computer virus"], "correct": 0},
    {"question": "What is a 'VPN' used for?", "options": ["Encrypting your connection", "A type of virus scan", "To speed up your PC"], "correct": 0},
]

# --- WII BOARD INTEGRATION START ---

# --- Global Variables for Board Input ---
# This dictionary will hold the raw weight values from the 4 sensors
weights = {
    'TR': 0, # Top-Right
    'TL': 0, # Top-Left
    'BR': 0, # Bottom-Right
    'BL': 0  # Bottom-Left
}
# This will be updated by the thread: 0 = stop, -1 = left, 1 = right
player_direction = 0
TILT_THRESHOLD = 2000 # We will need to tune this!

def find_balance_board():
    """Finds the Wii Balance Board from the list of input devices."""
    devices = [InputDevice(path) for path in list_devices()]
    for device in devices:
        # This is the exact name your board reported
        if device.name == "Nintendo Wii Remote Balance Board":
            print(f"Found Balance Board: {device.path}")
            return device
    return None

def balance_board_reader(device):
    """
    This function runs in a separate thread to constantly read
    data from the balance board.
    """
    global player_direction, weights
    try:
        # Get exclusive access to the device
        device.grab() 
        print("Balance Board thread started. Step on the board!")
        for event in device.read_loop():
            if event.type == ecodes.EV_ABS:
                # This is the exact sensor map we found for your board
                if event.code == ecodes.ABS_HAT0X:     # Top-Right (TR)
                    weights['TR'] = event.value
                elif event.code == ecodes.ABS_HAT1X:     # Top-Left (TL)
                    weights['TL'] = event.value
                elif event.code == ecodes.ABS_HAT0Y:     # Bottom-Right (BR)
                    weights['BR'] = event.value
                elif event.code == ecodes.ABS_HAT1Y:     # Bottom-Left (BL)
                    weights['BL'] = event.value
                
                # --- Calculate Tilt ---
                left_total = weights['TL'] + weights['BL']
                right_total = weights['TR'] + weights['BR']
                total_weight = left_total + right_total

                # Only register tilt if there is significant weight on the board
                if total_weight > 1000: # Adjust if needed
                    if left_total > right_total + TILT_THRESHOLD:
                        player_direction = -1 # Go Left
                    elif right_total > left_total + TILT_THRESHOLD:
                        player_direction = 1  # Go Right
                    else:
                        player_direction = 0  # Stop
                else:
                    player_direction = 0 # No one on the board
                    
    except Exception as e:
        print(f"Error reading from balance board: {e}")
        print("Please ensure you are running this script with 'sudo'")
        player_direction = 0 # Failsafe
    finally:
        if 'device' in locals() and device:
            device.ungrab()
# --- WII BOARD INTEGRATION END ---


class Particle:
    def __init__(self, x, y, color, size, life, angle, speed):
        self.x, self.y, self.color, self.size, self.life, self.angle, self.speed = x, y, color, size, life, angle, speed
    def update(self):
        self.life -= 1; self.size = max(0, self.size - 0.1)
        self.x += math.cos(self.angle) * self.speed; self.y += math.sin(self.angle) * self.speed
    def draw(self, surface):
        if self.life > 0: pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), int(self.size))

def create_explosion(particles_list, x, y):
    for _ in range(60):
        angle, speed = random.uniform(0, 2 * math.pi), random.uniform(1, 7)
        size, life = random.uniform(1, 5), random.randint(30, 60)
        color = random.choice([NEON_BLUE, ORANGE, WHITE])
        particles_list.append(Particle(x, y, color, size, life, angle, speed))

# NEW: Using DESIGN_WIDTH/HEIGHT for object positions
stars = [{"x": random.randint(0, DESIGN_WIDTH), "y": random.randint(0, DESIGN_HEIGHT), "speed": random.uniform(0.5, 2)} for _ in range(150)]
def update_and_draw_starfield(surface):
    surface.fill(BLACK)
    for star in stars:
        star["y"] += star["speed"]
        # NEW: Check against DESIGN_HEIGHT
        if star["y"] > DESIGN_HEIGHT: star["y"], star["x"] = 0, random.randint(0, DESIGN_WIDTH)
        brightness = int(100 + star["speed"] * 75); color = (brightness, brightness, brightness)
        pygame.draw.circle(surface, color, (star["x"], star["y"]), int(star["speed"]))

def get_player_id():
    player_id_str, input_active, error_message = "", True, ""
    while input_active:
        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN and len(player_id_str) > 0:
                    input_active = False
                elif event.key == pygame.K_BACKSPACE: player_id_str, error_message = player_id_str[:-1], ""
                # Allow only letters and limit length
                elif event.unicode.isalpha() and len(player_id_str) < 4: 
                    player_id_str += event.unicode.upper() # Use uppercase for consistent usernames
                    error_message = ""
        # NEW: Draw to the virtual 'screen'
        update_and_draw_starfield(screen)
        prompt_text = font.render("ENTER USERNAME (4 CHAR MAX):", True, NEON_BLUE); screen.blit(prompt_text, (DESIGN_WIDTH//2 - prompt_text.get_width()//2, 200))
        id_text = font.render(player_id_str, True, NEON_GREEN); screen.blit(id_text, (DESIGN_WIDTH//2 - id_text.get_width()//2, 260))
        if error_message:
            error_text = small_font.render(error_message, True, NEON_PINK); screen.blit(error_text, (DESIGN_WIDTH//2 - error_text.get_width()//2, 300))
        
        # NEW: Use the display helper to scale and flip
        update_display()
        clock.tick(FPS)
    return player_id_str

# --- Game Object Classes ---
class Player:
    def __init__(self):
        self.width, self.height = 35, 35
        # NEW: Use DESIGN_WIDTH/HEIGHT for positioning
        self.x, self.y = DESIGN_WIDTH // 2, DESIGN_HEIGHT - 100
        self.speed = PLAYER_SPEED; self.trail_particles = []
        self.has_shield = False; self.tilt, self.target_tilt = 0, 0
    def move(self, direction):
        if direction == "left": self.x -= self.speed; self.target_tilt = 20
        elif direction == "right": self.x += self.speed; self.target_tilt = -20
        # NEW: Use DESIGN_WIDTH for boundary check
        self.x = max(self.width, min(DESIGN_WIDTH - self.width, self.x))
    def update(self):
        self.tilt += (self.target_tilt - self.tilt) * 0.1
        if abs(self.tilt) < 0.1: self.tilt = 0
        self.target_tilt = 0
        exhaust_color = GOLD if self.has_shield else NEON_BLUE
        self.trail_particles.append(Particle(self.x, self.y + 20, exhaust_color, random.uniform(2, 4), 20, math.pi / 2 + random.uniform(-0.2, 0.2), random.uniform(2, 4)))
        [p.update() for p in self.trail_particles]; self.trail_particles = [p for p in self.trail_particles if p.life > 0]
    def draw(self):
        # All drawing commands already use 'screen' (which is now the virtual surface)
        [p.draw(screen) for p in self.trail_particles]
        ship_surface = pygame.Surface((50, 50), pygame.SRCALPHA); center = 25
        body_points = [(center, center - 18), (center - 15, center + 15), (center + 15, center + 15)]
        engine_points = [(center - 8, center + 12), (center + 8, center + 12), (center + 6, center + 18), (center - 6, center + 18)]
        wing_points_l = [(center - 13, center + 13), (center - 22, center + 10), (center - 10, center + 2)]
        wing_points_r = [(center + 13, center + 13), (center + 22, center + 10), (center + 10, center + 2)]
        pygame.draw.polygon(ship_surface, (40, 40, 40), engine_points)
        pygame.draw.polygon(ship_surface, NEON_BLUE, wing_points_l); pygame.draw.polygon(ship_surface, NEON_BLUE, wing_points_r)
        pygame.draw.polygon(ship_surface, (80, 80, 255), body_points)
        pygame.draw.polygon(ship_surface, WHITE, [(center, center - 12), (center - 3, center - 2), (center + 3, center - 2)])
        rotated_surface = pygame.transform.rotate(ship_surface, self.tilt)
        new_rect = rotated_surface.get_rect(center=(self.x, self.y + 10))
        screen.blit(rotated_surface, new_rect.topleft)
        if self.has_shield:
            shield_surface = pygame.Surface((80, 80), pygame.SRCALPHA)
            pygame.draw.circle(shield_surface, (*GOLD, 100), (40, 40), 38, 2)
            pygame.draw.circle(shield_surface, (*GOLD, 50), (40, 40), 40)
            screen.blit(shield_surface, (self.x - 40, self.y - 15))

class Obstacle:
    def __init__(self, game_time, obs_type=None, x_pos=None, y_pos=None, width=None, is_fire_wall=False):
        self.is_fire_wall = is_fire_wall
        self.type = obs_type if obs_type is not None else random.choice(['asteroid', 'drone', 'scout'])
        self.size = random.randint(35, 60)
        self.rotation_angle = random.randint(0, 360); self.rotation_speed = random.uniform(-2, 2)
        self.anim_timer = random.randint(0, 120)
        if self.type == 'asteroid': self.width, self.height = self.size, self.size; self.points = self._generate_asteroid_points()
        elif self.type == 'drone': self.width, self.height = 45, 35
        elif self.type == 'scout': self.width, self.height = 25, 35; self.trail_particles = []
        elif self.type == 'fire_wall_segment': self.width, self.height = width, 25; self.fire_particles = []; self.noise = PerlinNoise(octaves=2, seed=random.randint(0, 10000))
        # NEW: Use DESIGN_WIDTH for positioning
        self.x = x_pos if x_pos is not None else random.randint(0, DESIGN_WIDTH - self.width)
        self.y = y_pos if y_pos is not None else -self.height
        self.speed = 4 if self.is_fire_wall else OBSTACLE_SPEED + (game_time // 1000) * 0.5
    def _generate_asteroid_points(self):
        points = []; num_vertices = random.randint(7, 12)
        for i in range(num_vertices):
            angle = (i / num_vertices) * 2 * math.pi; dist = self.size / 2 * random.uniform(0.8, 1.2)
            points.append((dist * math.cos(angle), dist * math.sin(angle)))
        return points
    def update(self):
        self.y += self.speed; self.rotation_angle = (self.rotation_angle + self.rotation_speed) % 360; self.anim_timer += 1
        if self.type == 'scout':
            self.trail_particles.append(Particle(self.x + self.width/2, self.y, ORANGE, 2, 15, -math.pi/2, 2))
            [p.update() for p in self.trail_particles]; self.trail_particles = [p for p in self.trail_particles if p.life > 0]
        if self.type == 'fire_wall_segment':
            for _ in range(3):
                px = self.x + random.uniform(0, self.width); py = self.y + self.height
                noise_val = self.noise([px * 0.05, pygame.time.get_ticks() * 0.001])
                life, speed = 10 + int(abs(noise_val * 15)), 1 + abs(noise_val * 3)
                size, color = 2 + abs(noise_val * 4), random.choice([RED, ORANGE, GOLD])
                self.fire_particles.append(Particle(px, py, color, size, life, math.pi/2, speed))
            [p.update() for p in self.fire_particles]; self.fire_particles = [p for p in self.fire_particles if p.life > 0]
    def draw(self):
        center_x, center_y = self.x + self.width / 2, self.y + self.height / 2
        if self.type == 'asteroid':
            rotated_points = [(center_x + px*math.cos(math.radians(self.rotation_angle)) - py*math.sin(math.radians(self.rotation_angle)), center_y + px*math.sin(math.radians(self.rotation_angle)) + py*math.cos(math.radians(self.rotation_angle))) for px, py in self.points]
            pygame.draw.polygon(screen, (50, 50, 60), rotated_points); pygame.draw.polygon(screen, (180, 180, 220), rotated_points, 3)
            pygame.draw.circle(screen, NEON_BLUE, (center_x, center_y), 4)
        elif self.type == 'drone':
            pincer_angle = 20 + math.sin(self.anim_timer * 0.05) * 8
            pygame.draw.polygon(screen, (80,0,0), [(center_x, self.y), (self.x, self.y + self.height), (self.x+self.width, self.y + self.height)])
            pygame.draw.line(screen, RED, (center_x, self.y), (self.x - pincer_angle, self.y + self.height/1.5), 4)
            pygame.draw.line(screen, RED, (center_x, self.y), (self.x + self.width + pincer_angle, self.y + self.height/1.5), 4)
            eye_size = 4 + math.sin(self.anim_timer * 0.1) * 2
            pygame.draw.circle(screen, ORANGE, (center_x, self.y + 15), eye_size)
        elif self.type == 'scout':
            [p.draw(screen) for p in self.trail_particles]
            points = [(center_x, self.y), (self.x, self.y + self.height), (self.x + self.width, self.y + self.height)]
            pygame.draw.polygon(screen, PURPLE, points); pygame.draw.polygon(screen, NEON_PINK, points, 2)
        elif self.type == 'fire_wall_segment':
            [p.draw(screen) for p in self.fire_particles]
            pygame.draw.rect(screen, (40,0,0), (self.x, self.y, self.width, self.height))
    # NEW: Check against DESIGN_HEIGHT
    def off_screen(self): return self.y > DESIGN_HEIGHT

class Powerup:
    def __init__(self):
        # NEW: Use DESIGN_WIDTH
        self.size = 25; self.x, self.y = random.randint(0, DESIGN_WIDTH - self.size), -self.size
        self.speed = POWERUP_SPEED; self.rotation_angle, self.glow_radius, self.glow_direction = 0, 0, 1
    def move(self):
        self.y += self.speed; self.rotation_angle = (self.rotation_angle + 5) % 360; self.glow_radius += self.glow_direction
        if self.glow_radius >= 10 or self.glow_radius <= 0: self.glow_direction *= -1
    def draw(self):
        center_x, center_y = self.x + self.size // 2, self.y + self.size // 2
        glow_surface = pygame.Surface((self.size + 20, self.size + 20), pygame.SRCALPHA)
        pygame.draw.circle(glow_surface, (*NEON_GREEN, 50), (glow_surface.get_width()//2, glow_surface.get_height()//2), self.size//2 + self.glow_radius)
        screen.blit(glow_surface, (center_x - glow_surface.get_width()//2, center_y - glow_surface.get_height()//2))
        cross_surf = pygame.Surface((self.size, self.size), pygame.SRCALPHA)
        pygame.draw.rect(cross_surf, NEON_GREEN, (0, self.size//2 - 2, self.size, 4)); pygame.draw.rect(cross_surf, NEON_GREEN, (self.size//2 - 2, 0, 4, self.size))
        rotated_surf = pygame.transform.rotate(cross_surf, self.rotation_angle)
        screen.blit(rotated_surf, rotated_surf.get_rect(center=(center_x, center_y)))
    # NEW: Check against DESIGN_HEIGHT
    def off_screen(self): return self.y > DESIGN_HEIGHT

def ask_question():
    q = random.choice(questions); selected = None
    while selected is None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1: selected = 0
                elif event.key == pygame.K_2: selected = 1
                elif event.key == pygame.K_3: selected = 2
        
        # NEW: Draw to the virtual 'screen'
        update_and_draw_starfield(screen)
        q_text = small_font.render(q["question"], True, NEON_BLUE); screen.blit(q_text, (DESIGN_WIDTH//2 - q_text.get_width()//2, 100))
        for i, opt in enumerate(q["options"]):
            opt_text = small_font.render(f"{i+1}. {opt}", True, NEON_PINK); screen.blit(opt_text, (DESIGN_WIDTH//2 - opt_text.get_width()//2, 150 + i*40))
        
        # NEW: Use the display helper to scale and flip
        update_display()
        clock.tick(FPS)
    return selected == q["correct"]

def start_firewall_event(obstacles_list, powerups_list, game_time):
    obstacles_list.clear(); powerups_list.clear()
    # NEW: Use DESIGN_WIDTH
    num_walls, gap_width, last_gap_x = 5, 140, DESIGN_WIDTH // 2
    last_wall = None
    for i in range(num_walls):
        min_x = max(50, last_gap_x - 200)
        max_x = min(DESIGN_WIDTH - gap_width - 50, last_gap_x + 200)
        gap_x = random.randint(min_x, max_x)
        last_gap_x = gap_x
        y_pos = -100 - (i * 300)
        left_wall = Obstacle(game_time, obs_type='fire_wall_segment', x_pos=0, y_pos=y_pos, width=gap_x, is_fire_wall=True)
        # NEW: Use DESIGN_WIDTH
        right_wall = Obstacle(game_time, obs_type='fire_wall_segment', x_pos=gap_x + gap_width, y_pos=y_pos, width=DESIGN_WIDTH - (gap_x + gap_width), is_fire_wall=True)
        obstacles_list.extend([left_wall, right_wall])
        if i == num_walls - 1: last_wall = left_wall
    return last_wall

# --- NEW: SCORE SUBMISSION FUNCTION ---
def submit_score_to_firebase(user_id, score):
    """
    Submits the player's final score, username ('name'), and a timestamp to Firestore.
    Uses the 'highscores' collection to match the database structure.
    """
    global db # Use the initialized Firestore client

    if db is None:
        print("Score submission failed: Firebase not initialized.")
        return

    try:
        score_data = {
            # MATCHING YOUR DB STRUCTURE: 'name' and 'score'
            'name': user_id, 
            'score': int(score),
            'timestamp': datetime.datetime.now()
        }
        
        # Add a new document to the 'highscores' collection
        db.collection('highscores').add(score_data)
        print(f"Score for {user_id} ({int(score)}) submitted to Firebase successfully!")
        
    except Exception as e:
        print(f"Error submitting score to Firebase: {e}")
# --------------------------------------


def main():
    user_id = get_player_id()

    # --- WII BOARD INTEGRATION START ---
    # Try to find and connect to the board
    board = find_balance_board()
    
    if board is None:
        print("\n" + "="*40)
        print("!! ERROR: No Wii Balance Board found. !!")
        print("Make sure it's connected via Bluetooth.")
        print("You may need to run this with 'sudo'.")
        print("="*40 + "\n")
    else:
        # Start the balance board reader in its own thread
        reader_thread = threading.Thread(target=balance_board_reader, args=(board,), daemon=True)
        reader_thread.start()
    # --- WII BOARD INTEGRATION END ---

    while True:
        player = Player(); obstacles = []; powerups = []; particles = []
        # Cleaned variable initialization to prevent editor warnings
        score, game_time, combo_multiplier, combo_reset_timer, MAX_COMBO_TIME = 0.0, 0, 1.0, 0, FPS * 1.5
        game_over, is_firewall_event, last_firewall_wall, firewall_warning_timer = False, False, None, 0
        score_submitted = False # NEW: Flag to ensure score is only submitted once

        try: pygame.mixer.music.play(-1)
        except pygame.error: print("Could not play music loop.")
        explosion_created, death_sound_played = False, False
        running = True
        while running:
            clock.tick(FPS)
            for event in pygame.event.get():
                if event.type == pygame.QUIT: pygame.quit(); sys.exit()
                # NEW: Add a key to exit fullscreen (e.g., ESC)
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit()
                    if game_over and len(particles) == 0:
                        if event.key == pygame.K_r: user_id = get_player_id(); running = False
                
            if not game_over:
                game_time += 1; keys = pygame.key.get_pressed()
                player.target_tilt = 0

                # --- WII BOARD INTEGRATION START ---
                # Check for Wii Board movement
                if player_direction == -1: # Leaning left
                    player.move("left")
                elif player_direction == 1: # Leaning right
                    player.move("right")
                
                # Keyboard controls (as a fallback)
                if keys[pygame.K_LEFT]: player.move("left")
                if keys[pygame.K_RIGHT]: player.move("right")
                # --- WII BOARD INTEGRATION END ---
                
                player.update()
                if is_firewall_event:
                    # NEW: Check against DESIGN_HEIGHT
                    if last_firewall_wall and last_firewall_wall.y > DESIGN_HEIGHT: is_firewall_event = False
                else:
                    if random.randint(1, 100) < 4: # Reduced spawn rate
                        obstacles.append(Obstacle(game_time))
                    if random.randint(1, 600) < 2: powerups.append(Powerup())
                    if score >= 200 and random.randint(1, 1500) == 1:
                        is_firewall_event, firewall_warning_timer = True, 90
                        last_firewall_wall = start_firewall_event(obstacles, powerups, game_time)
                score += (1 / FPS) * combo_multiplier
                [obs.update() for obs in obstacles]; obstacles = [obs for obs in obstacles if not obs.off_screen()]
                [pup.move() for pup in powerups]; powerups = [pup for pup in powerups if not pup.off_screen()]
                player_rect = pygame.Rect(player.x - player.width/2, player.y, player.width, player.height)
                graze_rect = player_rect.inflate(60, 60)
                grazed_this_frame = False
                for obs in obstacles[:]:
                    obs_rect = pygame.Rect(obs.x, obs.y, obs.width, obs.height)
                    if player_rect.colliderect(obs_rect):
                        if player.has_shield: obstacles.remove(obs); player.has_shield = False
                        else: game_over = True
                    elif graze_rect.colliderect(obs_rect) and not is_firewall_event:
                        combo_multiplier = min(5.0, combo_multiplier + 0.05); combo_reset_timer = MAX_COMBO_TIME
                        grazed_this_frame = True
                if not grazed_this_frame and not is_firewall_event:
                    combo_reset_timer -= 1
                    if combo_reset_timer <= 0: combo_multiplier = max(1.0, combo_multiplier - 0.05)
                for pup in powerups[:]:
                    if player_rect.colliderect(pygame.Rect(pup.x, pup.y, pup.size, pup.size)):
                        powerups.remove(pup)
                        create_explosion(particles, pup.x + pup.size/2, pup.y + pup.size/2)
                        if ask_question(): score += 50; player.has_shield = True
                        
            # NEW: Draw everything to the virtual 'screen'
            update_and_draw_starfield(screen)
            
            if game_over and not explosion_created:
                create_explosion(particles, player.x, player.y + 15)
                explosion_created = True; pygame.mixer.music.stop()
                if dead_sound and not death_sound_played: dead_sound.play(); death_sound_played = True
                
            [p.update() for p in particles]; [p.draw(screen) for p in particles]
            particles = [p for p in particles if p.life > 0]
            
            if not game_over:
                player.draw(); [obs.draw() for obs in obstacles]; [pup.draw() for pup in powerups]
                score_text = font.render(f"SCORE: {int(score)}", True, WHITE); screen.blit(score_text, (10, 10))
                if not is_firewall_event:
                    combo_color = GOLD if combo_multiplier >= 5.0 else ORANGE
                    # NEW: Use DESIGN_WIDTH
                    combo_text = font.render(f"{combo_multiplier:.1f}x", True, combo_color); screen.blit(combo_text, (DESIGN_WIDTH - combo_text.get_width() - 10, 10))
                if firewall_warning_timer > 0:
                    warning_text = big_font.render("!! FIRE WALL !!", True, RED)
                    # NEW: Use DESIGN_WIDTH/HEIGHT
                    screen.blit(warning_text, (DESIGN_WIDTH//2 - warning_text.get_width()//2, DESIGN_HEIGHT//2 - 50))
                    firewall_warning_timer -= 1
            
            elif game_over and len(particles) == 0:
                # --- SCORE SUBMISSION TRIGGER ---
                if not score_submitted:
                    submit_score_to_firebase(user_id, score)
                    score_submitted = True
                # --------------------------------
                
                # NEW: Use DESIGN_WIDTH
                game_over_text = font.render("GAME OVER", True, NEON_PINK); screen.blit(game_over_text, (DESIGN_WIDTH//2 - game_over_text.get_width()//2, 220))
                final_score_text = small_font.render(f"Final Score: {int(score)}", True, WHITE); screen.blit(final_score_text, (DESIGN_WIDTH//2 - final_score_text.get_width()//2, 270))
                restart_text = small_font.render("R to Play Again", True, NEON_BLUE); screen.blit(restart_text, (DESIGN_WIDTH//2 - restart_text.get_width()//2, 320))
            
            # NEW: Use the display helper to scale and flip
            update_display()

if __name__ == "__main__":
    main()
