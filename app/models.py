from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, id, fullname, email, role):
        self.id = id
        self.fullname = fullname
        self.email = email
        self.role = role
