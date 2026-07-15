import React, { useState } from 'react';

/**
 * Input that lets the user enter a Quebec agricultural parcel ID.
 * Props:
 *   onSelect: (parcelId: string) => void
 */
export default function ParcelSelector({ onSelect }) {
  const [parcelId, setParcelId] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (parcelId.trim()) {
      onSelect(parcelId.trim());
    }
  };

  return (
    <form className="parcel-selector" onSubmit={handleSubmit} data-testid="parcel-selector">
      <label htmlFor="parcel-id" className="parcel-selector__label">
        Parcel ID
      </label>
      <input
        id="parcel-id"
        type="text"
        className="parcel-selector__input"
        value={parcelId}
        onChange={(e) => setParcelId(e.target.value)}
        placeholder="e.g. 10042"
      />
      <button type="submit" className="parcel-selector__button">
        Load parcel
      </button>
    </form>
  );
}
