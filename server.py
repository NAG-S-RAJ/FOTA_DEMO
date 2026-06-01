from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi import UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uvicorn
import json
import os
import uuid

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

pending_tbms = {}
connected_tbms = {}

campaigns = []
logs = []


def add_log(msg):

    print(msg)

    logs.append(msg)

    if len(logs) > 500:
        logs.pop(0)

@app.delete("/campaign/{campaign_id}")
async def delete_campaign(campaign_id: str):

    global campaigns

    campaigns = [
        c for c in campaigns
        if c["campaign_id"] != campaign_id
    ]

    add_log(
        f"Campaign Deleted: {campaign_id}"
    )

    return {
        "status": "deleted"
    }
# ======================
# BASIC APIS
# ======================

@app.get("/")
async def root():

    return {
        "status": "running"
    }


@app.get("/pending")
async def pending():

    return {
        "pending": list(
            pending_tbms.keys()
        )
    }


@app.get("/tbms")
async def tbms():

    return {
        "online_tbms": list(
            connected_tbms.keys()
        )
    }


@app.get("/logs")
async def get_logs():

    return logs


@app.get("/campaigns")
async def get_campaigns():

    return campaigns


# ======================
# FILE UPLOAD
# ======================

@app.post("/upload")
async def upload(
    file: UploadFile = File(...)
):

    path = os.path.join(
        UPLOAD_FOLDER,
        file.filename
    )

    with open(path, "wb") as f:

        f.write(
            await file.read()
        )

    add_log(
        f"Firmware Uploaded: {file.filename}"
    )

    return {
        "status": "success",
        "file": file.filename
    }


@app.get("/files/{filename}")
async def file_download(
    filename: str
):

    path = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    return FileResponse(
        path,
        filename=filename
    )


# ======================
# APPROVE / REJECT
# ======================

@app.post("/approve/{vin}")
async def approve(vin: str):

    if vin not in pending_tbms:

        return {
            "status": "not_found"
        }

    ws = pending_tbms[vin]

    connected_tbms[vin] = ws

    del pending_tbms[vin]

    await ws.send_text(
        json.dumps({
            "type": "approved"
        })
    )

    add_log(
        f"{vin} approved"
    )

    return {
        "status": "approved"
    }


@app.post("/reject/{vin}")
async def reject(vin: str):

    if vin not in pending_tbms:

        return {
            "status": "not_found"
        }

    ws = pending_tbms[vin]

    await ws.send_text(
        json.dumps({
            "type": "rejected"
        })
    )

    await ws.close()

    del pending_tbms[vin]

    add_log(
        f"{vin} rejected"
    )

    return {
        "status": "rejected"
    }


# ======================
# CREATE CAMPAIGN
# ======================

@app.post("/campaign")
async def campaign(
    vin: str,
    campaign_name: str,
    firmware_file: str
):

    if vin not in connected_tbms:

        return {
            "status": "TBM_NOT_CONNECTED"
        }

    campaign_id = str(
        uuid.uuid4()
    )

    base_url = os.getenv(
        "PUBLIC_URL",
        "https://fota-demo.onrender.com"
    )

    download_url = (
        f"{base_url}/files/{firmware_file}"
    )

    campaign_info = {

        "campaign_id": campaign_id,

        "vin": vin,

        "campaign_name": campaign_name,

        "firmware_file": firmware_file,

        "status": "sent"
    }

    campaigns.append(
        campaign_info
    )

    ws = connected_tbms[vin]

    await ws.send_text(
        json.dumps({

            "type": "campaign",

            "campaign_id": campaign_id,

            "campaign_name": campaign_name,

            "firmware_file": firmware_file,

            "download_url": download_url

        })
    )

    add_log(
        f"Campaign Sent -> {vin}"
    )

    return {
        "status": "sent"
    }


# ======================
# WEBSOCKET
# ======================

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket
):

    await websocket.accept()

    vin = None

    try:

        while True:

            raw = await websocket.receive_text()

            add_log(
                f"RX: {raw}"
            )

            data = json.loads(raw)

            msg_type = data.get(
                "type"
            )

            if msg_type == "register_request":

                vin = data["vin"]
                # Remove stale entries
                if vin in pending_tbms:
                    del pending_tbms[vin]

                if vin in connected_tbms:
                    del connected_tbms[vin]

                pending_tbms[vin] = websocket

                add_log(
                    f"Connection Request: {vin}"
                )

            elif msg_type == "heartbeat":

                add_log(
                    f"Heartbeat Received -> {vin}"
                )

            elif msg_type == "campaign_ack":

                add_log(
                    f"{vin} campaign acknowledged"
                )

            elif msg_type == "progress":

                add_log(
                    f"{vin} progress "
                    f"{data['progress']}%"
                )

            elif msg_type == "completed":

                add_log(
                    f"{vin} update completed"
                )

            elif msg_type == "status_response":

                add_log(
                    f"{vin}: "
                    f"{data['status']}"
                )

    except WebSocketDisconnect:

        add_log(
            f"{vin} disconnected"
        )

    finally:

        if vin in pending_tbms:
            del pending_tbms[vin]

        if vin in connected_tbms:
            del connected_tbms[vin]


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            8000
        )
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
