"""XP, levels, streaks and achievements (used by attendance and tasks)."""
from database import get_db
from datetime import date, datetime, timedelta
from psycopg2.extras import RealDictCursor
from services.notifications import create_notification


def _ensure_gamification_profile(c, employee_id):
    c.execute("""
        INSERT INTO employee_gamification (employee_id)
        VALUES (%s)
        ON CONFLICT (employee_id) DO NOTHING
    """, (employee_id,))


def _calculate_level(xp):
    # Every 100 XP advances the employee by one level.
    return max(1, int(xp) // 100 + 1)


def award_xp(employee_id, xp, reason, reference_type=None, reference_key=None):
    """Award XP once for a specific reference, then return the new profile."""
    if not employee_id or not xp:
        return None

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:
        _ensure_gamification_profile(c, employee_id)

        # Reference-based awards are idempotent, preventing duplicate XP when a
        # route is refreshed or the same completion event is submitted twice.
        if reference_type is not None and reference_key is not None:
            c.execute("""
                SELECT id
                FROM xp_transactions
                WHERE employee_id=%s
                  AND reference_type=%s
                  AND reference_key=%s
                LIMIT 1
            """, (employee_id, reference_type, str(reference_key)))
            if c.fetchone():
                c.execute("""
                    SELECT * FROM employee_gamification
                    WHERE employee_id=%s
                """, (employee_id,))
                profile = c.fetchone()
                conn.close()
                return profile

        c.execute("""
            INSERT INTO xp_transactions
                (employee_id, xp, reason, reference_type, reference_key)
            VALUES (%s, %s, %s, %s, %s)
        """, (employee_id, xp, reason, reference_type,
              str(reference_key) if reference_key is not None else None))

        c.execute("""
            UPDATE employee_gamification
            SET xp = xp + %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE employee_id=%s
        """, (xp, employee_id))

        c.execute("""
            UPDATE employee_gamification
            SET level = GREATEST(1, (xp / 100) + 1)
            WHERE employee_id=%s
        """, (employee_id,))

        conn.commit()

        c.execute("""
            SELECT * FROM employee_gamification
            WHERE employee_id=%s
        """, (employee_id,))
        profile = c.fetchone()
        return profile

    except Exception as e:
        conn.rollback()
        print('AWARD XP ERROR:', repr(e))
        return None
    finally:
        conn.close()


def update_attendance_streak(employee_id, attendance_date):
    """Update consecutive attendance days and return current/longest streak."""
    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:
        _ensure_gamification_profile(c, employee_id)

        c.execute("""
            SELECT last_attendance_date, current_streak, longest_streak
            FROM employee_gamification
            WHERE employee_id=%s
            FOR UPDATE
        """, (employee_id,))
        profile = c.fetchone()

        last_date = profile['last_attendance_date'] if profile else None
        current = int(profile['current_streak'] or 0) if profile else 0
        longest = int(profile['longest_streak'] or 0) if profile else 0

        if last_date == attendance_date:
            return current, longest

        if last_date == attendance_date - timedelta(days=1):
            current += 1
        else:
            current = 1

        longest = max(longest, current)

        c.execute("""
            UPDATE employee_gamification
            SET current_streak=%s,
                longest_streak=%s,
                last_attendance_date=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE employee_id=%s
        """, (current, longest, attendance_date, employee_id))

        conn.commit()
        return current, longest

    except Exception as e:
        conn.rollback()
        print('UPDATE ATTENDANCE STREAK ERROR:', repr(e))
        return 0, 0
    finally:
        conn.close()


def award_achievement(employee_id, code):
    """Award an achievement once and grant its XP reward."""
    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:
        c.execute("""
            SELECT id, name, description, icon, xp_reward
            FROM achievements
            WHERE code=%s
        """, (code,))
        achievement = c.fetchone()
        if not achievement:
            conn.close()
            return False

        c.execute("""
            INSERT INTO employee_achievements
                (employee_id, achievement_id)
            VALUES (%s, %s)
            ON CONFLICT (employee_id, achievement_id) DO NOTHING
            RETURNING achievement_id
        """, (employee_id, achievement['id']))
        inserted = c.fetchone()

        if not inserted:
            conn.rollback()
            return False

        conn.commit()

    except Exception as e:
        conn.rollback()
        print('AWARD ACHIEVEMENT ERROR:', repr(e))
        return False
    finally:
        conn.close()

    if achievement['xp_reward']:
        award_xp(
            employee_id,
            achievement['xp_reward'],
            f"Achievement unlocked: {achievement['name']}",
            'achievement',
            code
        )

    try:
        create_notification(
            employee_id,
            f"🏆 Achievement unlocked: {achievement['name']} (+{achievement['xp_reward']} XP)"
        )
    except Exception as e:
        print('ACHIEVEMENT NOTIFICATION ERROR:', repr(e))

    return True


def process_attendance_rewards(employee_id, attendance_dt):
    """Apply attendance XP, streaks and one-time attendance achievements."""
    attendance_date = attendance_dt.date() if isinstance(attendance_dt, datetime) else attendance_dt

    # Daily attendance XP is keyed by date, so repeated check-ins cannot farm XP.
    award_xp(
        employee_id,
        10,
        'Daily attendance check-in',
        'attendance_day',
        attendance_date.isoformat()
    )

    current_streak, longest_streak = update_attendance_streak(
        employee_id, attendance_date
    )

    award_achievement(employee_id, 'first_step')

    if isinstance(attendance_dt, datetime) and attendance_dt.hour < 9:
        award_xp(
            employee_id,
            15,
            'Early Bird check-in',
            'early_bird_day',
            attendance_date.isoformat()
        )
        award_achievement(employee_id, 'early_bird')

    if current_streak >= 5:
        award_achievement(employee_id, 'five_day_streak')
    if current_streak >= 10:
        award_achievement(employee_id, 'ten_day_streak')
    if current_streak >= 30:
        award_achievement(employee_id, 'thirty_day_streak')

    return current_streak, longest_streak


def process_task_completion_rewards(employee_id, task_id, deadline=None, completed_at=None):
    """Award task completion XP and an on-time bonus."""
    award_xp(
        employee_id,
        20,
        'Task completed',
        'task_completion',
        task_id
    )

    if completed_at is None:
        completed_at = datetime.now()

    deadline_date = None
    if isinstance(deadline, datetime):
        deadline_date = deadline.date()
    elif isinstance(deadline, date):
        deadline_date = deadline
    elif isinstance(deadline, str) and deadline:
        try:
            deadline_date = datetime.strptime(deadline[:10], '%Y-%m-%d').date()
        except (ValueError, TypeError):
            deadline_date = None

    if deadline_date and completed_at.date() <= deadline_date:
        award_xp(
            employee_id,
            10,
            'Task completed before deadline',
            'task_on_time',
            task_id
        )

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)
    try:
        c.execute("""
            SELECT COUNT(*) AS count
            FROM tasks
            WHERE assigned_to=%s
              AND status='Completed'
        """, (employee_id,))
        completed_count = c.fetchone()['count']
    finally:
        conn.close()

    award_achievement(employee_id, 'task_finisher')
    if completed_count >= 10:
        award_achievement(employee_id, 'ten_tasks')
