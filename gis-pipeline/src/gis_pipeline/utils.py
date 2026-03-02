import logging


def generate_processing_report(log: logging.Logger, report_data: dict):
    """
    Generate and log a summary report of the geoprocessing pipeline.
    Args:
        report_data: Dictionary with keys 'vector_data', 'raster_data', each containing
                            a dict with 'processed', 'errors', 'skipped' counts.
    """
    log.info("-" * 60)
    log.info("PROCESSING REPORT SUMMARY")
    log.info("-" * 60)

    for i, data_type in enumerate(sorted(report_data.keys()), start=1):
        stats = report_data[data_type]
        log.info(f"{i}. {data_type.replace('_', ' ').capitalize()}:")
        for stat_name, value in stats.items():
            log.info(f"    {stat_name.capitalize():<25}: {value}")
        log.info("-" * 60)


def add_section_to_logger(log: logging.Logger, section_title: str) -> None:
    """
    Add a section title to the logger output.
    """
    log.info("-" * 60)
    log.info(section_title)
    log.info("-" * 60)


def add_process_to_logger(log: logging.Logger, process_title: str) -> None:
    """
    Add a process title to the logger output.
    """
    log.info(f"[PROCESS]: {process_title}")
