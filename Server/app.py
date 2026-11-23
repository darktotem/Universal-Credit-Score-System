from flask import Flask, request, jsonify
from config import Config
from extensions import db, migrate, bcrypt
from flasgger import Swagger

from models import  User, Post

