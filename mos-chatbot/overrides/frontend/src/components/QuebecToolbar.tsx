import React from 'react';

const QUICK_PROMPTS = [
  {
    label: 'SOM potential here',
    prompt: 'What is the soil organic matter potential at my current location?',
  },
  {
    label: 'Available datasets',
    prompt: 'What soil datasets are available for Quebec?',
  },
  {
    label: 'Analyse parcel',
    prompt: 'Analyse the selected parcel for soil carbon sequestration potential.',
  },
];

/**
 * Toolbar with mos-gis-specific quick-action buttons.
 * Props:
 *   onPrompt: (promptText: string) => void — fires when user clicks a button
 */
export default function QuebecToolbar({ onPrompt }) {
  return (
    <div className="quebec-toolbar" data-testid="quebec-toolbar">
      {QUICK_PROMPTS.map(({ label, prompt }) => (
        <button
          key={label}
          type="button"
          className="quebec-toolbar__button"
          onClick={() => onPrompt(prompt)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
