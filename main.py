import libtorrent as lt
import os
import time
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
import tempfile
import shutil
from typing import List
import json

app = FastAPI()

# Configure CORS with specific origins
origins = [
    "http://localhost:5173",  # Vite's default development server
    "http://127.0.0.1:5173",  # Alternative localhost
    "http://localhost:3000",  # Common React development port
    "http://127.0.0.1:3000",  # Alternative localhost
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Store active torrent sessions
active_sessions = {}

class TorrentSession:
    def __init__(self, torrent_path: str, save_path: str):
        self.torrent_path = torrent_path
        self.session = lt.session()
        self.session.listen_on(6881, 6891)
        self.torrent_info = lt.torrent_info(torrent_path)
        self.handle = self.session.add_torrent({
            'ti': self.torrent_info,
            'save_path': save_path
        })
        self.handle.set_sequential_download(True)
        self.last_progress = 0

    def get_progress(self):
        status = self.handle.status()
        return {
            'progress': status.progress * 100,
            'download_rate': status.download_rate,
            'upload_rate': status.upload_rate,
            'num_peers': status.num_peers
        }


@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    try:
        # Save the uploaded file temporarily
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Create torrent file (add only the uploaded file)
        fs = lt.file_storage()
        lt.add_files(fs, file_path)
        t = lt.create_torrent(fs)
        t.add_tracker("udp://tracker.opentrackr.org:1337/announce")
        t.set_creator("EchoFlix")
        t.set_comment("EchoFlix Video Stream")

# ✅ Generate piece hashes
        lt.set_piece_hashes(t, os.path.dirname(file_path))
        torrent_path = file_path + ".torrent"
        with open(torrent_path, "wb") as f:
            f.write(lt.bencode(t.generate()))

        # ✅ Store torrent_path and save_path
        session_id = str(time.time())
        active_sessions[session_id] = TorrentSession(torrent_path, os.path.dirname(file_path))

        return {"session_id": session_id, "filename": file.filename}
    except Exception as e:
        print("UPLOAD ERROR:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stream/{session_id}")
async def stream_video(session_id: str):
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = active_sessions[session_id]
    status = session.handle.status()
    
    if status.progress < 0.1:  # Wait for initial buffer
        return {"status": "buffering", "progress": status.progress * 100}
    
    # Stream the video file
    video_path = session.torrent_info.files().file_path(0)
    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename=os.path.basename(video_path)
    )

@app.get("/status/{session_id}")
async def get_status(session_id: str):
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return active_sessions[session_id].get_progress()

@app.get("/download/{session_id}")
async def download_torrent(session_id: str):
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = active_sessions[session_id]
    torrent_path = session.torrent_path  # ✅ use the real path

    if not os.path.exists(torrent_path):
        raise HTTPException(status_code=404, detail="Torrent file not found")

    return FileResponse(
        torrent_path,
        media_type="application/x-bittorrent",
        filename=os.path.basename(torrent_path)
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 