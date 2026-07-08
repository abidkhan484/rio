import { ComponentStatesUpdateContext } from "../componentManagement";
import { ComponentBase, ComponentState, DeltaState } from "./componentBase";

export type WebviewState = ComponentState & {
    _type_: "Webview-builtin";
    content: string; // Url or Html code
    enable_pointer_events: boolean;
    resize_to_fit_content: boolean;
};

export class WebviewComponent extends ComponentBase<WebviewState> {
    private iframe: HTMLIFrameElement | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private isInitialized = false;
    private boundMessageHandler: ((event: MessageEvent) => void) | null = null;

    createElement(context: ComponentStatesUpdateContext): HTMLElement {
        let element = document.createElement("div");
        element.classList.add("rio-webview");

        this.boundMessageHandler = (event: MessageEvent) => {
            if (event.data?.type !== "rioWebviewMessage") return;

            if (this.iframe !== null) {
                if (event.source !== this.iframe.contentWindow) return;
            } else {
                if (event.data.webviewId !== this.id) return;
            }

            this.sendMessageToBackend(event.data.payload);
        };
        window.addEventListener("message", this.boundMessageHandler);

        return element;
    }

    onDestruction(): void {
        super.onDestruction();
        if (this.boundMessageHandler !== null) {
            window.removeEventListener("message", this.boundMessageHandler);
            this.boundMessageHandler = null;
        }
    }

    updateElement(
        deltaState: DeltaState<WebviewState>,
        context: ComponentStatesUpdateContext
    ): void {
        super.updateElement(deltaState, context);

        if (deltaState.content !== undefined) {
            // If the URL/HTML hasn't actually changed from last time, don't do
            // anything. This is important so scripts don't get re-executed each
            // time the component is updated.
            if (
                deltaState.content !== this.state.content ||
                !this.isInitialized
            ) {
                if (isUrl(deltaState.content)) {
                    this.element.innerHTML = "";

                    this.iframe = this.createIframe();
                    this.iframe.src = deltaState.content;

                    this.element.appendChild(this.iframe);
                } else if (requiresIframe(deltaState.content)) {
                    this.element.innerHTML = "";

                    this.iframe = this.createIframe();
                    this.iframe.srcdoc = injectRioSendMessageForIframe(
                        deltaState.content
                    );

                    this.element.appendChild(this.iframe);
                } else {
                    // Clean up stuff we no longer need
                    this.iframe = null;
                    this.resizeObserver = null;

                    // Load the HTML
                    this.element.innerHTML = deltaState.content;

                    // Just setting the innerHTML doesn't run scripts. Do that
                    // manually.
                    this.runScriptsInElement();
                }

                this.isInitialized = true;
            }
        }

        if (deltaState.enable_pointer_events !== undefined) {
            this.element.style.pointerEvents = deltaState.enable_pointer_events
                ? "auto"
                : "none";
        }

        if (
            deltaState.resize_to_fit_content !== undefined &&
            this.iframe !== null
        ) {
            if (deltaState.resize_to_fit_content) {
                if (this.resizeObserver === null) {
                    this.resizeObserver = tryCreateIframeResizeObserver(
                        this.iframe
                    );
                }
            } else {
                if (this.resizeObserver !== null) {
                    this.resizeObserver.disconnect();
                    this.resizeObserver = null;

                    this.iframe.style.removeProperty("min-width");
                    this.iframe.style.removeProperty("min-height");
                }
            }
        }
    }

    createIframe(): HTMLIFrameElement {
        let iframe = document.createElement("iframe");

        let self = this;
        iframe.addEventListener("load", function () {
            // Careful, this code runs with a delay! If this iframe has
            // already been replaced by other content, do nothing.
            if (
                self.iframe !== iframe ||
                self.resizeObserver !== null ||
                !self.state.resize_to_fit_content
            ) {
                return;
            }

            self.resizeObserver = tryCreateIframeResizeObserver(iframe);
        });

        return iframe;
    }

    runScriptsInElement(): void {
        for (let oldScriptElement of this.element.querySelectorAll("script")) {
            // Create a new script element
            const newScriptElement = document.createElement("script");

            // Copy over all attributes
            for (let i = 0; i < oldScriptElement.attributes.length; i++) {
                const attr = oldScriptElement.attributes[i];
                newScriptElement.setAttribute(attr.name, attr.value);
            }

            // Inject rioSendMessage for inline scripts. External scripts
            // (those with a `src` attribute) are not modified.
            //
            // Use `var` so that multiple scripts within the same Webview can
            // each declare rioSendMessage without causing redeclaration errors.
            let content = oldScriptElement.innerHTML;
            if (!oldScriptElement.hasAttribute("src")) {
                content =
                    `var rioSendMessage=function(payload){window.parent.postMessage({type:"rioWebviewMessage",webviewId:${this.id},payload:payload},"*")};` +
                    content;
            }

            // And the source itself
            newScriptElement.appendChild(document.createTextNode(content));

            // Finally replace the old script element with the new one so
            // the browser executes it
            oldScriptElement.parentNode!.replaceChild(
                newScriptElement,
                oldScriptElement
            );
        }
    }
}

function injectRioSendMessageForIframe(html: string): string {
    const scriptTag =
        '<script>var rioSendMessage=function(payload){parent.postMessage({type:"rioWebviewMessage",payload:payload},"*")}</script>';

    const closeHeadMatch = html.match(/<\/head>/i);
    if (closeHeadMatch !== null) {
        const insertPos = closeHeadMatch.index!;
        return html.slice(0, insertPos) + scriptTag + html.slice(insertPos);
    }

    return scriptTag + html;
}

function isUrl(urlOrHtml: string): boolean {
    try {
        new URL(urlOrHtml);
        return true;
    } catch (error) {
        return false;
    }
}

function requiresIframe(html: string): boolean {
    return html.match(/^\s*(<!doctype |<html[ >])/i) !== null;
}

function tryCreateIframeResizeObserver(
    iframe: HTMLIFrameElement
): ResizeObserver | null {
    let contentDoc = iframe.contentDocument;
    if (contentDoc === null) {
        return null;
    }

    let docElement = contentDoc.documentElement;

    let resizeObserver = new ResizeObserver(function () {
        iframe.style.minWidth = `${docElement.scrollWidth}px`;
        iframe.style.minHeight = `${docElement.scrollHeight}px`;
    });
    resizeObserver.observe(docElement);

    return resizeObserver;
}
