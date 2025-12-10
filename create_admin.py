"""
Script to create the first admin user for the admin panel.
Run this after setting up the database.

Usage:
    python create_admin.py
"""

import asyncio
import getpass
from db import Database, AdminUser
from config import load_env
import passlib.hash


async def create_admin():
    """Create admin user interactively."""
    print("=" * 50)
    print("Create Admin User for Seedream Admin Panel")
    print("=" * 50)
    print()

    # Get admin details
    username = input("Enter admin username: ").strip()
    if not username:
        print("Error: Username cannot be empty")
        return

    email = input("Enter admin email (optional, press Enter to skip): ").strip() or None

    password = getpass.getpass("Enter admin password: ")
    password_confirm = getpass.getpass("Confirm password: ")

    if password != password_confirm:
        print("Error: Passwords do not match")
        return

    if len(password) < 8:
        print("Error: Password must be at least 8 characters")
        return

    # Hash password
    password_hash = passlib.hash.bcrypt.hash(password)

    # Connect to database
    settings = load_env()
    db = await Database.create(settings.database_url)

    try:
        async with db.session() as session:
            # Check if admin already exists
            from sqlalchemy import select

            result = await session.execute(
                select(AdminUser).where(AdminUser.username == username)
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"\nError: Admin user '{username}' already exists")
                return

            # Create admin
            admin = AdminUser(
                username=username,
                email=email,
                password_hash=password_hash,
                is_active=True,
                is_superuser=True,
            )

            session.add(admin)
            await session.commit()

            print("\n" + "=" * 50)
            print("✓ Admin user created successfully!")
            print("=" * 50)
            print(f"Username: {username}")
            print(f"Email: {email or 'N/A'}")
            print(f"Superuser: Yes")
            print("\nYou can now login to the admin panel at:")
            print("http://localhost:8001/admin/login")
            print("=" * 50)

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(create_admin())
