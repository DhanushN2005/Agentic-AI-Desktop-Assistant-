"""
Registry for all Atomic Actions that must execute directly
without invoking the semantic planner.
"""

ATOMIC_ACTIONS = {
    "app_op",          # open_app, close_app
    "vision_capture",  # take_picture (screen)
    "camera_capture",  # take_picture (camera)
    "file_save",       # save_picture, save file
    "file_delete",     # delete file
    "file_rename",     # rename file
    "file_op",         # manage folder
    "browser_op",      # navigate_url
    "browser_navigate",# navigate
    "browser_control", # click, type, copy, paste
    "system_op",       # volume_up, volume_down, brightness
    "media"            # play/pause
}
