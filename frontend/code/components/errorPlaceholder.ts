import { applyIcon } from '../designApplication';
import { ComponentBase, ComponentState } from './componentBase';

export type BuildFailedState = ComponentState & {
    _type_: 'BuildFailed-builtin';
    error_summary: string;
    error_details: string;
};

export class ErrorPlaceholderComponent extends ComponentBase {
    state: Required<BuildFailedState>;

    private iconElement: HTMLElement;
    private summaryElement: HTMLElement;
    private detailsElement: HTMLElement;

    createElement(): HTMLElement {
        // Create the elements
        let element = document.createElement('div');
        element.classList.add('rio-error-placeholder');

        element.innerHTML = `
            <div class="rio-error-placeholder-top"></div>
            <div class="rio-error-placeholder-content">
                <div class="rio-error-placeholder-header">
                    <div class="rio-error-placeholder-icon"></div>
                    <div class="rio-error-placeholder-summary"></div>
                </div>
                <div class="rio-error-placeholder-details"></div>
            </div>
            <div class="rio-error-placeholder-bottom"></div>
        `;

        // Expose them
        this.iconElement = element.querySelector(
            '.rio-error-placeholder-icon'
        ) as HTMLElement;

        this.summaryElement = element.querySelector(
            '.rio-error-placeholder-summary'
        ) as HTMLElement;

        this.detailsElement = element.querySelector(
            '.rio-error-placeholder-details'
        ) as HTMLElement;

        // And initialize them
        applyIcon(
            this.iconElement,
            'material/error:fill',
            'var(--rio-global-danger-fg)'
        );

        return element;
    }

    updateElement(
        deltaState: BuildFailedState,
        latentComponents: Set<ComponentBase>
    ): void {
        super.updateElement(deltaState, latentComponents);

        if (deltaState.error_summary !== undefined) {
            this.summaryElement.innerText = deltaState.error_summary;
        }

        if (deltaState.error_details !== undefined) {
            this.detailsElement.innerText = deltaState.error_details;
        }
    }
}