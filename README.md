# FitUni-Platform - Fitness Partner Matching Platform

FitUni is a web application that connects university students with compatible fitness partners based on shared sports interests, schedules, and locations. Built with Flask, PostgreSQL, and a Tailwind CSS frontend, it features secure user authentication, dynamic profile management, a machine learning-based matching algorithm, and email notifications. This project demonstrates skills in full-stack development, database design, and responsive UI creation.

## Features

- **User Authentication**: Secure signup/signin with email verification and reCAPTCHA.
- **Profile Management**: Users can specify sports, skill levels, availability (weekly or one-time), and preferences, with dynamic form interactions.
- **Matching Algorithm**: Employs TF-IDF and cosine similarity to match users based on sports, schedules, and preferences, with a Tinder-like swipe interface.
- **Booking System**: Send, accept, or reject workout requests with time slot and sport selection.
- **Chat System**: Real-time messaging between matched users.
- **Email Notifications**: Automated emails for verification, likes, chat messages, and workout requests.
- **Responsive UI**: Tailwind CSS (via CDN) with Swiper.js for interactive matching, Font Awesome icons, and smooth animations.
- **Privacy & Terms**: Detailed privacy policy and terms of use, compliant with data protection standards.

## Tech Stack

- **Backend**: Python, Flask
- **Database**: PostgreSQL with psycopg2
- **Frontend**: HTML, Tailwind CSS (CDN), JavaScript, Jinja2, Swiper.js, Font Awesome
- **Machine Learning**: scikit-learn (TF-IDF, cosine similarity)
- **Email Service**: Flask-Mail with SMTP
- **Security**: bcrypt for password hashing, reCAPTCHA for bot protection
- **Logging**: Python logging for debugging

## Setup Instructions

### Prerequisites
- Python 3.8+
- PostgreSQL
- Virtual environment (recommended)

### Installation
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/anhhont/fituni-platform.git
   cd fituni-platform


Set Up a Virtual Environment:
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate


Install Dependencies:
pip install -r requirements.txt


Set Up Environment Variables:Create a .env file in the project root:
FLASK_SECRET_KEY=your-secret-key
DATABASE_URL=your-postgresql-url
RECAPTCHA_PUBLIC_KEY=your-recaptcha-public-key
RECAPTCHA_SECRET_KEY=your-recaptcha-secret-key
MAIL_USERNAME=your-email@example.com
MAIL_PASSWORD=your-email-password


Initialize the Database:Run the application to create tables:
python app.py


Run the Application:
python app.py

Access at http://localhost:5000.


Usage

Sign Up: Register with a university email and verify with a 4-digit code sent to your email.
Complete Profile: Add sports, skill levels, availability, and preferences via an interactive form.
Find Matches: Browse potential partners using a swipeable interface or select specific matches.
Send Requests: Propose workout sessions with specific times and sports.
Chat: Communicate with matched partners to plan workouts.

Project Structure
fituni-platform/
├── app.py              # Main Flask application
├── templates/          # HTML templates
│   ├── base.html
│   ├── bookings.html
│   ├── chat.html
│   ├── dashboard.html
│   ├── find_instructor.html
│   ├── find_match.html
│   ├── landing.html
│   ├── match.html
│   ├── privacy.html
│   ├── profile.html
│   ├── select_workout.html
│   ├── signin.html
│   ├── signup.html
│   ├── terms.html
│   ├── verify.html
├── .gitignore         # Git ignore file
├── requirements.txt   # Python dependencies
├── .env.example       # Example environment variables
├── LICENSE            # MIT License
├── README.md          # This file

GitHub Best Practices

Clear README: Details project overview, setup, and usage.
.gitignore: Excludes sensitive files (.env, venv/, __pycache__/).
License: MIT License for open-source sharing.
Requirements File: Lists all Python dependencies.
Environment Variables: Sensitive data stored in .env.
Code Organization: Modular backend and frontend with 15 Jinja2 templates.
Frontend: Responsive design with Tailwind CSS (CDN), Swiper.js for swipeable matching, and dynamic forms (e.g., profile time slots).

License
This project is licensed under the MIT License. See the LICENSE file for details.
Contact
For questions or feedback, reach out via hi@hnta.xyz or open an issue on GitHub.

Note: This is a sanitized version of the original project, with sensitive data (e.g., reCAPTCHA keys, university references, location lists) removed or generalized.```