from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, LargeBinary,
    ForeignKey, Index,
)
from sqlalchemy.orm import relationship
from database.connection import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    folder_path = Column(Text, nullable=False)
    name = Column(String(255))
    status = Column(String(50), default="created")  # created / scanning / ready / completed
    file_count = Column(Integer, default=0)
    image_count = Column(Integer, default=0)
    video_count = Column(Integer, default=0)
    other_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    files = relationship("File", back_populates="task", cascade="all, delete-orphan")
    duplicate_groups = relationship("DuplicateGroup", back_populates="task", cascade="all, delete-orphan")


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        Index("ix_files_task_id", "task_id"),
        Index("ix_files_sha256", "sha256"),
        Index("ix_files_file_size", "file_size"),
    )

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    file_path = Column(Text, nullable=False)
    relative_path = Column(Text, nullable=False)
    file_name = Column(String(512), nullable=False)
    extension = Column(String(32))
    file_size = Column(Integer)
    file_type = Column(String(32))  # image / video / other
    mime_type = Column(String(128))
    sha256 = Column(String(64))
    xxhash_partial = Column(String(32))
    dhash = Column(String(16))
    hash_version = Column(Integer, default=1)
    clip_feature = Column(LargeBinary)
    has_exif = Column(Boolean, default=False)
    exif_time = Column(DateTime)
    file_created = Column(DateTime)
    file_modified = Column(DateTime)
    best_time = Column(DateTime)
    time_source = Column(String(32))
    time_anomaly = Column(Text)
    has_gps = Column(Boolean, default=False)
    gps_lat = Column(Float)
    gps_lng = Column(Float)
    thumbnail_path = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    task = relationship("Task", back_populates="files")


class DuplicateGroup(Base):
    __tablename__ = "duplicate_groups"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    group_type = Column(String(32))  # exact / similar
    similarity = Column(Float)
    file_count = Column(Integer)
    recommended_keep_id = Column(Integer, ForeignKey("files.id"))

    task = relationship("Task", back_populates="duplicate_groups")
    members = relationship("DuplicateGroupMember", back_populates="group", cascade="all, delete-orphan")


class DuplicateGroupMember(Base):
    __tablename__ = "duplicate_group_members"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("duplicate_groups.id"), nullable=False)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    is_recommended = Column(Boolean, default=False)
    user_action = Column(String(32))  # keep / delete / null

    group = relationship("DuplicateGroup", back_populates="members")
    file = relationship("File")


class GpxMatch(Base):
    __tablename__ = "gpx_matches"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    gpx_file_path = Column(Text)
    matched_lat = Column(Float)
    matched_lng = Column(Float)
    time_offset_sec = Column(Integer)
    match_quality = Column(String(32))  # good / warning / no_match
    user_confirmed = Column(Boolean, default=False)
    original_has_gps = Column(Boolean, default=False)


class AiLabel(Base):
    __tablename__ = "ai_labels"
    __table_args__ = (
        Index("ix_ai_labels_file_task", "file_id", "task_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    user_label = Column(String(32))  # keep / delete / null
    labeled_at = Column(DateTime)
    ai_prediction = Column(String(32))  # keep / delete / null
    ai_confidence = Column(Float)
    ai_raw_score = Column(Float)  # 0.0~1.0 raw keep probability
    predicted_at = Column(DateTime)
    model_version = Column(Integer)
    is_training_data = Column(Boolean, default=False)
    label_source = Column(String(32))  # manual / correction


class AiModelVersion(Base):
    __tablename__ = "ai_model_versions"

    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False, unique=True)
    model_path = Column(Text, nullable=False)
    training_samples = Column(Integer)
    keep_samples = Column(Integer)
    delete_samples = Column(Integer)
    val_accuracy = Column(Float)
    val_precision = Column(Float)
    val_recall = Column(Float)
    val_f1 = Column(Float)
    training_time_sec = Column(Float)
    created_at = Column(DateTime, default=datetime.now)
    is_current = Column(Boolean, default=False)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer)
    operation_type = Column(String(32))  # delete / move / rename / exif_write / gps_write / ai_label
    file_path = Column(Text)
    target_path = Column(Text)
    detail = Column(Text)  # JSON
    created_at = Column(DateTime, default=datetime.now)
