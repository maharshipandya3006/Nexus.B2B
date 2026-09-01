import sqlite3
import os
import sys
from app.config import settings

def run_migration():
    db_path = settings.SQLITE_DATABASE_PATH
    if not os.path.exists(db_path):
        print(f"Database file not found at {db_path}, skipping migration (will be created automatically).")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # Check if transactions table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions';")
        if not cursor.fetchone():
            print("Table 'transactions' does not exist yet. Skipping.")
            return

        # Check if column already exists
        cursor.execute("PRAGMA table_info(transactions);")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "transaction_number" not in columns:
            print("Adding 'transaction_number' column to 'transactions' table...")
            cursor.execute("ALTER TABLE transactions ADD COLUMN transaction_number TEXT;")
            print("Column 'transaction_number' added successfully.")
        else:
            print("Column 'transaction_number' already exists.")

        # Backfill existing rows
        cursor.execute("SELECT id FROM transactions WHERE transaction_number IS NULL OR transaction_number = '';")
        unpopulated_rows = cursor.fetchall()
        for (row_id,) in unpopulated_rows:
            tx_num = f"NXS-{row_id:04d}"
            cursor.execute("UPDATE transactions SET transaction_number = ? WHERE id = ?;", (tx_num, row_id))
        
        # Create index if not exists
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_transactions_transaction_number ON transactions (transaction_number);")
        
        conn.commit()
        print(f"Migration completed successfully. Backfilled {len(unpopulated_rows)} rows.")
    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    run_migration()
