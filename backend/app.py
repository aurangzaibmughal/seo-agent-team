import gradio as gr
from app.main import app as fastapi_app

with gr.Blocks(title="SEO Agent Backend API") as demo:
    gr.Markdown("# 🚀 Autonomous Multi-Agent SEO Engine API")
    gr.Markdown(
        """
        Backend API is live and serving requests!
        - **Interactive API Documentation:** [/docs](/docs)
        - **Root Health Check:** [/](/)
        """
    )

app = gr.mount_gradio_app(fastapi_app, demo, path="/gradio")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860)
