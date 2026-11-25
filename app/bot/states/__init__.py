"""FSM states. Persisted in Redis so progress survives restarts."""

from aiogram.fsm.state import State, StatesGroup


class UploadStates(StatesGroup):
    waiting_file = State()


class ProfileEditStates(StatesGroup):
    waiting_value = State()


class SettingsStates(StatesGroup):
    waiting_other_cv_language = State()
