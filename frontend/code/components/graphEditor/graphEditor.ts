import { ComponentId } from "../../dataModels";
import { ComponentBase, ComponentState } from "../componentBase";
import { pixelsPerRem } from "../../app";
import { NodeInputComponent } from "../nodeInput";
import { NodeOutputComponent } from "../nodeOutput";
import {
    AugmentedConnectionState,
    AugmentedNodeState,
    GraphStore,
    NodeState,
} from "./graphStore";
import { DraggingConnectionStrategy } from "./draggingConnectionStrategy";
import { DraggingSelectionStrategy } from "./draggingSelectionStrategy";
import { DraggingNodesStrategy } from "./draggingNodesStrategy";
import {
    devel_getComponentByKey,
    getNodeFromPort,
    getPortFromCircle,
    makeConnectionElement,
    updateConnectionFromObject,
} from "./utils";

export type GraphEditorState = ComponentState & {
    _type_: "GraphEditor-builtin";
    children?: ComponentId[];
};

export class GraphEditorComponent extends ComponentBase {
    declare state: Required<GraphEditorState>;

    private htmlChild: HTMLElement;
    public svgChild: SVGSVGElement;

    private selectionChild: HTMLElement;

    public graphStore: GraphStore = new GraphStore();

    // When clicking & dragging a variety of things can happen based on the
    // selection, mouse button, position and phase of the moon. This strategy
    // object is used in lieu of if-else chains.
    private dragStrategy:
        | DraggingConnectionStrategy
        | DraggingSelectionStrategy
        | DraggingNodesStrategy
        | null = null;

    createElement(): HTMLElement {
        // Create the HTML
        let element = document.createElement("div");
        element.classList.add("rio-graph-editor");

        this.svgChild = document.createElementNS(
            "http://www.w3.org/2000/svg",
            "svg"
        );
        element.appendChild(this.svgChild);

        this.htmlChild = document.createElement("div");
        element.appendChild(this.htmlChild);

        this.selectionChild = document.createElement("div");
        this.selectionChild.classList.add("rio-graph-editor-selection");
        this.selectionChild.style.opacity = "0";
        this.htmlChild.appendChild(this.selectionChild);

        // Listen for drag events. The exact nature of the drag event is
        // determined by the current drag strategy.
        this.addDragHandler({
            element: element,
            onStart: this._onDragStart.bind(this),
            onMove: this._onDragMove.bind(this),
            onEnd: this._onDragEnd.bind(this),
            capturing: true,
        });

        return element;
    }

    updateElement(
        deltaState: GraphEditorState,
        latentComponents: Set<ComponentBase>
    ): void {
        // Spawn some children for testing
        if (deltaState.children !== undefined) {
            // Spawn all nodes
            for (let ii = 0; ii < deltaState.children.length; ii++) {
                let childId = deltaState.children[ii];

                let rawNode: NodeState = {
                    id: childId,
                    title: `Node ${ii}`,
                    left: 10 + ii * 10,
                    top: 10 + ii * 10,
                };
                let augmentedNode = this._makeNode(latentComponents, rawNode);
                this.graphStore.addNode(augmentedNode);
            }

            // Connect some of them
            requestAnimationFrame(() => {
                let fromPortComponent = devel_getComponentByKey("out_1");
                let toPortComponent = devel_getComponentByKey("in_1");

                let connectionElement = makeConnectionElement();
                this.svgChild.appendChild(connectionElement);

                let augmentedConn: AugmentedConnectionState = {
                    // @ts-ignore
                    fromNode: deltaState.children[1],
                    fromPort: fromPortComponent.id,
                    // @ts-ignore
                    toNode: deltaState.children[2],
                    toPort: toPortComponent.id,
                    element: connectionElement,
                };
                this.graphStore.addConnection(augmentedConn);
                updateConnectionFromObject(augmentedConn);
            });
        }
    }

    _onDragStart(event: PointerEvent): boolean {
        // If a drag strategy is already active, ignore this event
        if (this.dragStrategy !== null) {
            return false;
        }

        // FIXME: A lot of the strategies below are checking for the left mouse
        // button. This is wrong on touch and pointer devices.

        // Find an applicable strategy
        //
        // Case: New connection from a port
        let targetElement = event.target as HTMLElement;
        console.assert(
            targetElement !== null,
            "Pointer event has no target element"
        );

        if (
            event.button === 0 &&
            targetElement.classList.contains("rio-graph-editor-port-circle")
        ) {
            let portComponent = getPortFromCircle(targetElement);

            // Add a new connection to the SVG
            let connectionElement = makeConnectionElement();
            this.svgChild.appendChild(connectionElement);

            // Store the strategy
            this.dragStrategy = new DraggingConnectionStrategy(
                getNodeFromPort(portComponent).id,
                portComponent.id,
                connectionElement
            );

            return true;
        }

        // Case: Move around the selected nodes
        if (event.button === 0 && false) {
            // Make sure all selected nodes are on top
            //
            // TODO
            //
            // nodeElement.style.zIndex = "1";

            // Store the strategy
            this.dragStrategy = new DraggingNodesStrategy();

            // Accept the drag
            return true;
        }

        // Case: Rectangle selection
        if (event.button === 0) {
            // Store the strategy
            this.dragStrategy = new DraggingSelectionStrategy(
                event.clientX,
                event.clientY
            );

            // Accept the drag
            return true;
        }

        // No strategy found
        console.assert(
            this.dragStrategy === null,
            "A drag strategy was found, but the function hasn't returned"
        );
        return false;
    }

    _onDragMove(event: PointerEvent): void {
        // If no drag strategy is active, there's nothing to do
        if (this.dragStrategy === null) {
            return;
        }

        // Delegate to the drag strategy
        this.dragStrategy.onDragMove(this, event);
    }

    _onDragEnd(event: PointerEvent): void {
        // If no drag strategy is active, there's nothing to do
        if (this.dragStrategy === null) {
            return;
        }

        // Delegate to the drag strategy
        this.dragStrategy.onDragEnd(this, event);

        // Clear the drag strategy
        this.dragStrategy = null;
    }

    /// Creates a node element and adds it to the HTML child. Returns the node
    /// state, augmented with the HTML element.
    _makeNode(
        latentComponents: Set<ComponentBase>,
        nodeState: NodeState
    ): AugmentedNodeState {
        // Build the node HTML
        const nodeElement = document.createElement("div");
        nodeElement.dataset.nodeId = nodeState.id.toString();
        nodeElement.classList.add(
            "rio-graph-editor-node",
            "rio-switcheroo-neutral"
        );
        nodeElement.style.left = `${nodeState.left}rem`;
        nodeElement.style.top = `${nodeState.top}rem`;
        this.htmlChild.appendChild(nodeElement);

        // Header
        const header = document.createElement("div");
        header.classList.add("rio-graph-editor-node-header");
        header.innerText = nodeState.title;
        nodeElement.appendChild(header);

        // Body
        const nodeBody = document.createElement("div");
        nodeBody.classList.add("rio-graph-editor-node-body");
        nodeElement.appendChild(nodeBody);

        // Content
        this.replaceOnlyChild(latentComponents, nodeState.id, nodeBody);

        // Build the augmented node state
        let augmentedNode = { ...nodeState } as AugmentedNodeState;
        augmentedNode.element = nodeElement;

        return augmentedNode;
    }
}
