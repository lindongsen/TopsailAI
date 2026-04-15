'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: SQLAlchemy implementation for Message storage
'''

from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, String, Text, DateTime, Index, asc
from sqlalchemy.orm import Session as SQLSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import desc

from .base import MessageStorageBase
from .base import MessageData
from .constants import (
    MESSAGE_ROLE_USER,
    MESSAGE_ROLE_ASSISTANT,
)

Base = declarative_base()


class Message(Base, MessageStorageBase):
    """SQLAlchemy Message model"""
    __tablename__ = MessageStorageBase.tb_message

    msg_id = Column(String(32), primary_key=True)
    session_id = Column(String(32), primary_key=True)
    message = Column(Text, nullable=False)
    role = Column(String(32), nullable=False, default="user")
    create_time = Column(DateTime, nullable=False, default=datetime.now)
    update_time = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    task_id = Column(String(32), nullable=True, index=True)
    task_result = Column(Text, nullable=True)

    # Index for efficient queries
    __table_args__ = (
        Index('idx_message_session_create', 'session_id', 'create_time'),
    )


class MessageSQLAlchemy(MessageStorageBase):
    """SQLAlchemy implementation of Message storage"""

    def __init__(self, engine):
        self.engine = engine
        Base.metadata.create_all(engine)

    def get_engine(self):
        """Get the SQLAlchemy engine"""
        return self.engine

    @staticmethod
    def _to_data(message: Message) -> MessageData:
        """Convert SQLAlchemy model to MessageData"""
        return MessageData(
            msg_id=message.msg_id,
            session_id=message.session_id,
            message=message.message,
            role=message.role,
            create_time=message.create_time,
            update_time=message.update_time,
            task_id=message.task_id,
            task_result=message.task_result
        )

    def create(self, message_data: MessageData) -> bool:
        """Create a new message"""
        with SQLSession(self.engine) as db:
            message = Message(
                msg_id=message_data.msg_id,
                session_id=message_data.session_id,
                message=message_data.message,
                role=message_data.role or MESSAGE_ROLE_USER,
                create_time=message_data.create_time or datetime.now(),
                update_time=message_data.update_time or datetime.now(),
                task_id=message_data.task_id,
                task_result=message_data.task_result
            )
            db.add(message)
            db.commit()
        return True

    def get(self, msg_id: str, session_id: str) -> Optional[MessageData]:
        """Get a message by msg_id and session_id"""
        with SQLSession(self.engine) as db:
            message = db.query(Message).filter(
                Message.msg_id == msg_id,
                Message.session_id == session_id
            ).first()
            if message:
                return self._to_data(message)
            return None

    def get_by_session(self, session_id: str) -> List[MessageData]:
        """Get all messages for a session"""
        with SQLSession(self.engine) as db:
            messages = db.query(Message).filter(
                Message.session_id == session_id
            ).order_by(desc(Message.create_time)).all()
            return [self._to_data(m) for m in messages]

    def get_by_session_sorted(
        self,
        session_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        sort_key: str = "create_time",
        order_by: str = "desc",
        offset: int = 0,
        limit: int = 1000
    ) -> List[MessageData]:
        """Get messages for a session with sorting and filtering"""
        with SQLSession(self.engine) as db:
            query = db.query(Message).filter(Message.session_id == session_id)

            # Apply time filters
            if start_time:
                query = query.filter(Message.create_time >= start_time)
            if end_time:
                query = query.filter(Message.create_time <= end_time)

            # Apply sorting
            sort_column = getattr(Message, sort_key, Message.create_time)
            if order_by == "asc":
                query = query.order_by(asc(sort_column))
            else:
                query = query.order_by(desc(sort_column))

            # Apply pagination
            messages = query.offset(offset).limit(limit).all()
            return [self._to_data(m) for m in messages]

    def get_latest_message(self, session_id: str) -> Optional[MessageData]:
        """Get the latest message for a session"""
        with SQLSession(self.engine) as db:
            message = db.query(Message).filter(
                Message.session_id == session_id
            ).order_by(desc(Message.create_time)).first()
            if message:
                return self._to_data(message)
            return None

    def get_unprocessed_messages(self, session_id: str, processed_msg_id: str, to_include_role_assistant: bool=False) -> List[MessageData]:
        """Get unprocessed messages after the processed_msg_id.

        Returns ALL messages after processed_msg_id, regardless of role.
        Role filtering is handled at the formatting level (format_pending_messages).

        Args:
            session_id: The session identifier
            processed_msg_id: The last processed message ID. If None or empty, returns all messages.
            to_include_role_assistant: # From Human: DONOT REMOVE THIS ARG
        """
        with SQLSession(self.engine) as db:
            # Handle None/empty processed_msg_id - return all messages for the session
            if not processed_msg_id:
                messages = db.query(Message).filter(
                    Message.session_id == session_id
                ).order_by(asc(Message.create_time)).all()
                return [self._to_data(m) for m in messages]

            # First get the create_time of the processed message
            processed_msg = db.query(Message).filter(
                Message.msg_id == processed_msg_id,
                Message.session_id == session_id
            ).first()

            if not processed_msg:
                # If processed_msg_id not found, return all messages for the session
                messages = db.query(Message).filter(
                    Message.session_id == session_id
                ).order_by(asc(Message.create_time)).all()
            else:
                # From Human: The message that the assistant should be removed by default is the previous response
                # From Human: This control role filtering method cannot be removed
                roles = [MESSAGE_ROLE_USER, ""]
                if to_include_role_assistant:
                    roles.append(MESSAGE_ROLE_ASSISTANT)

                # Get ALL messages created after the processed message (regardless of role)
                # Exclude processed_msg_id itself
                messages = db.query(Message).filter(
                    Message.session_id == session_id,
                    Message.msg_id != processed_msg_id,
                    Message.create_time >= processed_msg.create_time,
                    Message.role.in_(roles),
                ).order_by(asc(Message.create_time)).all()

            return [self._to_data(m) for m in messages]

    def get_messages_since(self, since: datetime) -> List[MessageData]:
        """Get all messages created since the specified time"""
        with SQLSession(self.engine) as db:
            messages = db.query(Message).filter(
                Message.create_time >= since
            ).all()
            return [self._to_data(m) for m in messages]

    def update_task_info(
        self,
        msg_id: str,
        session_id: str,
        task_id: Optional[str],
        task_result: Optional[str]
    ) -> Optional[MessageData]:
        """Update task_id and task_result for a message"""
        with SQLSession(self.engine) as db:
            message = db.query(Message).filter(
                Message.msg_id == msg_id,
                Message.session_id == session_id
            ).first()

            if message:
                message.task_id = task_id
                message.task_result = task_result
                message.update_time = datetime.now()
                db.commit()
                return self._to_data(message)
            return None

    def delete_by_session(self, session_id: str) -> bool:
        """Delete all messages for a session (alias for delete_messages_by_session)"""
        count = self.delete_messages_by_session(session_id)
        return count >= 0

    def delete_by_session_id(self, session_id: str) -> int:
        """
        Delete all messages for a session by session_id.

        This method is used by the delete_sessions API endpoint to cascade delete
        messages when a session is deleted.

        Args:
            session_id (str): The session identifier.

        Returns:
            int: Number of messages deleted.
        """
        with SQLSession(self.engine) as db:
            count = db.query(Message).filter(
                Message.session_id == session_id
            ).delete()
            db.commit()
            return count

    def delete_messages_by_session(self, session_id: str) -> int:
        """Delete all messages for a session"""
        with SQLSession(self.engine) as db:
            count = db.query(Message).filter(
                Message.session_id == session_id
            ).delete()
            db.commit()
            return count

    def delete(self, msg_id: str, session_id: str) -> bool:
        """Delete a single message by msg_id and session_id"""
        with SQLSession(self.engine) as db:
            count = db.query(Message).filter(
                Message.msg_id == msg_id,
                Message.session_id == session_id
            ).delete()
            db.commit()
            return count > 0

    def update(self, message_data: MessageData) -> bool:
        """Update an existing message"""
        with SQLSession(self.engine) as db:
            message = db.query(Message).filter(
                Message.msg_id == message_data.msg_id,
                Message.session_id == message_data.session_id
            ).first()

            if message:
                message.message = message_data.message
                message.role = message_data.role
                message.task_id = message_data.task_id
                message.task_result = message_data.task_result
                message.update_time = datetime.now()
                db.commit()
                return True
            return False

    def get_recent_messages(self, since: datetime) -> List[MessageData]:
        """Get all messages created since the specified time (alias for get_messages_since)"""
        return self.get_messages_since(since)

    def get_messages(
        self,
        session_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 1000,
        sort_key: str = "create_time",
        order_by: str = "desc"
    ) -> List[MessageData]:
        """Get messages for a session with filtering, sorting, and pagination"""
        return self.get_by_session_sorted(
            session_id=session_id,
            start_time=start_time,
            end_time=end_time,
            sort_key=sort_key,
            order_by=order_by,
            offset=offset,
            limit=limit
        )

    def add_message(self, msg: MessageData):
        """Add a message to the storage if it doesn't exist"""
        with SQLSession(self.engine) as db:
            # Check if message already exists
            existing = db.query(Message).filter(
                Message.msg_id == msg.msg_id,
                Message.session_id == msg.session_id
            ).first()

            if not existing:
                message = Message(
                    msg_id=msg.msg_id,
                    session_id=msg.session_id,
                    message=msg.message,
                    role=msg.role or "user",
                    create_time=msg.create_time or datetime.now(),
                    update_time=msg.update_time or datetime.now(),
                    task_id=msg.task_id,
                    task_result=msg.task_result
                )
                db.add(message)
                db.commit()

    def get_message(self, msg_id: str) -> Optional[MessageData]:
        """Retrieve a single message by its msg_id"""
        with SQLSession(self.engine) as db:
            message = db.query(Message).filter(
                Message.msg_id == msg_id
            ).first()
            if message:
                return self._to_data(message)
            return None

    def get_messages_by_session(self, session_id: str) -> List[MessageData]:
        """Retrieve all messages for a session, ordered by create_time descending"""
        return self.get_by_session(session_id)

    def del_messages(self, msg_id: str = None, session_id: str = None):
        """Delete messages from storage based on msg_id or session_id"""
        with SQLSession(self.engine) as db:
            if session_id:
                db.query(Message).filter(
                    Message.session_id == session_id
                ).delete()
            if msg_id:
                db.query(Message).filter(
                    Message.msg_id == msg_id
                ).delete()
            db.commit()

    def clean_messages(self, before_seconds: int, session_id: str = None) -> int:
        """Delete messages older than the specified seconds"""
        with SQLSession(self.engine) as db:
            cutoff_time = datetime.now().timestamp() - before_seconds
            cutoff_datetime = datetime.fromtimestamp(cutoff_time)

            query = db.query(Message).filter(
                Message.create_time < cutoff_datetime
            )

            if session_id:
                query = query.filter(Message.session_id == session_id)

            count = query.delete()
            db.commit()
            return count