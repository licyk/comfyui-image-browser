"""ComfyUI entry point; the image browser is provided without workflow nodes."""


async def comfy_entrypoint():
    from .comfyui_image_browser.extension import ImageBrowserExtension

    return ImageBrowserExtension()


WEB_DIRECTORY = "./js"
__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]
