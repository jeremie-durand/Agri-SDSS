// ------------------ شماره‌گذاری زمین‌ها ------------------
var indexedFields = fields.toList(fields.size());
fields = ee.FeatureCollection(
  ee.List.sequence(0, fields.size().subtract(1)).map(function(i) {
    var f = ee.Feature(indexedFields.get(i));
    return f.set('FIELD_ID', i);
  })
);

// ------------------ Spatial Join: پیدا کردن زمین‌هایی با حداقل یک نمونه خاک ------------------
var spatialFilter = ee.Filter.intersects({ leftField: '.geo', rightField: '.geo' });
var saveJoin = ee.Join.saveAll({ matchesKey: 'matchedSamples' });
var joined = saveJoin.apply(fields, soil_samples, spatialFilter);

var fieldsWithSamples = ee.FeatureCollection(joined.map(function(f) {
  var samples = ee.List(f.get('matchedSamples'));
  var count = samples.size();
  return ee.Feature(f).set('sampleCount', count);
})).filter(ee.Filter.gt('sampleCount', 0));

// ------------------ استخراج نقاط نمونه داخل زمین‌های معتبر ------------------
var filteredSamples = soil_samples.filterBounds(fieldsWithSamples.geometry());

// ------------------ برچسب‌گذاری نمونه‌ها با نوع خاک ------------------
var labeledSamples = filteredSamples.map(function(sample) {
  var matchedSoil = soil_boundaries.filterBounds(sample.geometry()).first();
  var soilSymbol = ee.Algorithms.If(matchedSoil, matchedSoil.get('SYMBOL'), null);
  return sample.set('soilType', soilSymbol);
});

// ------------------ محاسبه آمار نمونه‌ها در هر زمین ------------------
var fieldStats = fieldsWithSamples.map(function(field) {
  var geom = field.geometry();
  var samplesInField = labeledSamples.filterBounds(geom);

  var somStats = samplesInField.reduceColumns({
    reducer: ee.Reducer.mean()
              .combine({reducer2: ee.Reducer.stdDev(), sharedInputs: true})
              .combine({reducer2: ee.Reducer.count(), sharedInputs: true}),
    selectors: ['SOM']
  });

  var soilTypes = samplesInField.aggregate_array('soilType').distinct();
  var soilTypeCount = soilTypes.size();  

  return field.set({
    FIELD_ID: field.get('FIELD_ID'),
    sampleCount: somStats.get('count'),
    mean_SOM: somStats.get('mean'),
    stdDev_SOM: somStats.get('stdDev'),
    soilTypes: soilTypes,
    soilTypeCount: soilTypeCount
  });
});

// ------------------ فیلتر زمین‌هایی که حداقل یک نوع خاک دارند ------------------
var fieldStatsFiltered = fieldStats.filter(ee.Filter.gt('soilTypeCount', 0));

// ------------------ خروجی CSV ------------------
Export.table.toDrive({
  collection: fieldStatsFiltered,
  description: 'Field_SOM_Stats_Filtered',
  fileFormat: 'CSV',
  selectors: ['FIELD_ID', 'sampleCount', 'mean_SOM', 'stdDev_SOM', 'soilTypes']
});

////////////////////////// Ta inja hameh dadehayeh zamini ro darim ///////////
// ------------------ پارامترها ------------------
var year = 2023;

// ------------------ تقسیم زمین‌ها به 5 بخش ------------------
var total = fieldStatsFiltered.size();
var list = fieldStatsFiltered.toList(total);
var size = total.divide(5).floor();

var part1 = ee.FeatureCollection(list.slice(0, size));
var part2 = ee.FeatureCollection(list.slice(size, size.multiply(2)));
var part3 = ee.FeatureCollection(list.slice(size.multiply(2), size.multiply(3)));
var part4 = ee.FeatureCollection(list.slice(size.multiply(3), size.multiply(4)));
var part5 = ee.FeatureCollection(list.slice(size.multiply(4), total));

// 🟡 تغییر این قسمت بسته به پارت مورد نظر
var currentFields = part4;

// ------------------ بارگذاری تصاویر Sentinel-2 ------------------
var images = ee.ImageCollection("COPERNICUS/S2_SR")
  .filterBounds(currentFields.geometry())
  .filter(ee.Filter.calendarRange(year, year, 'year'))
  .filter(ee.Filter.or(
    ee.Filter.calendarRange(4, 6, 'month'),
    ee.Filter.calendarRange(9, 12, 'month')
  ))
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 1));

// ------------------ تعریف شاخص‌ها ------------------
function addIndices(img) {
  var RED = img.select('B4');
  var GREEN = img.select('B3');
  var BLUE = img.select('B2');
  var NIR = img.select('B8');
  var SWIR = img.select('B11');

  var ndvi = img.normalizedDifference(['B8', 'B4']).rename('NDVI');
  var bsi = img.expression('((SWIR + RED) - (NIR + BLUE)) / ((SWIR + RED) + (NIR + BLUE))',
              {'SWIR': SWIR, 'RED': RED, 'NIR': NIR, 'BLUE': BLUE}).rename('BSI');
  var savi = img.expression('1.5 * ((NIR - RED) / (NIR + RED + 0.5))',
              {'NIR': NIR, 'RED': RED}).rename('SAVI');
  var ndmi = img.normalizedDifference(['B8', 'B11']).rename('NDMI');
  var ci = img.expression('(RED - GREEN) / (RED + GREEN)', {'RED': RED, 'GREEN': GREEN}).rename('CI');
  var omi = img.expression('1 / pow(GREEN, 2)', {'GREEN': GREEN}).rename('OMI');
  var evi = img.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
              {'NIR': NIR, 'RED': RED, 'BLUE': BLUE}).rename('EVI');
  var si = img.expression('(RED - BLUE) / (RED + BLUE)', {'RED': RED, 'BLUE': BLUE}).rename('SI');
  var ri = img.expression('pow(RED, 2) / (BLUE * pow(GREEN, 2))',
              {'RED': RED, 'BLUE': BLUE, 'GREEN': GREEN}).rename('RI');
  var cai = img.expression('0.5 * ((SWIR - NIR) - (RED - BLUE))',
              {'SWIR': SWIR, 'NIR': NIR, 'RED': RED, 'BLUE': BLUE}).rename('CAI');
  var bi = img.expression(
    'sqrt((pow(B2, 2) + pow(B3, 2) + pow(B4, 2)) / 3)',
    {'B2': BLUE, 'B3': GREEN, 'B4': RED}
  ).rename('BI');

  var ndsi = img.normalizedDifference(['B3', 'B11']).rename('NDSI');
  var snowMask = ndsi.lte(0.4);

  return img.updateMask(snowMask)
            .addBands([ndvi, bsi, savi, ndmi, ci, omi, evi, si, ri, cai, bi])
            .copyProperties(img, ['system:time_start']);
}

// ------------------ اعمال شاخص‌ها ------------------
var withIndices = images.map(addIndices);

// ------------------ لایه‌های ثابت توپوگرافی و اقلیمی ------------------
// DEM 30m پایدار: NASADEM
var dem30 = ee.Image('NASA/NASADEM_HGT/001').select('elevation');
var terrain = ee.Terrain.products(dem30).select(['elevation','slope','aspect']);

// WorldClim BIO (BIO1 = Annual Mean Temp*10, BIO12 = Annual Precipitation)
var worldclim = ee.Image('WORLDCLIM/V1/BIO').select(['bio01','bio12']).rename(['BIO1','BIO12']);

// ------------------ استخراج ویژگی‌ها برای هر تصویر و زمین ------------------
var features = withIndices.map(function(img) {
  return ee.FeatureCollection(currentFields.map(function(field) {
    var geom = field.geometry();
    var indexed = ee.Image(img);

    // میانگین BSI
    var bsiMean = indexed.select('BSI').reduceRegion({
      reducer: ee.Reducer.mean(),
      geometry: geom,
      scale: 10,
      maxPixels: 1e8,
      bestEffort: true
    }).get('BSI');

    return ee.Algorithms.If(
      bsiMean,
      (function() {
        var bareMask = indexed.select('BSI').gt(ee.Number(bsiMean));
        var masked = indexed.updateMask(bareMask);

        var stats = masked.reduceRegion({
          reducer: ee.Reducer.mean().combine({reducer2: ee.Reducer.stdDev(), sharedInputs: true}),
          geometry: geom,
          scale: 10,
          maxPixels: 1e8,
          bestEffort: true
        });

        // Topography (ثابت)
        var topoStats = terrain.reduceRegion({
          reducer: ee.Reducer.mean().combine({reducer2: ee.Reducer.stdDev(), sharedInputs: true}),
          geometry: geom,
          scale: 30,
          maxPixels: 1e8,
          bestEffort: true
        });

        // Climate (ثابت)
        var climStats = worldclim.reduceRegion({
          reducer: ee.Reducer.mean().combine({reducer2: ee.Reducer.stdDev(), sharedInputs: true}),
          geometry: geom,
          scale: 1000,
          maxPixels: 1e8,
          bestEffort: true
        });

        var date = ee.Date(img.get('system:time_start'));
        var imgID = ee.Number(year).format('%d').cat('_').cat(date.format('MMdd'));

        return ee.Feature(null, stats)
          .set('FIELD_ID', field.get('FIELD_ID'))
          .set('Image_ID', imgID)
          .set('mean_SOM', field.get('mean_SOM'))
          .set('stdDev_SOM', field.get('stdDev_SOM'))
          .set('soilTypes', field.get('soilTypes'))
          .set('valid', 1)
          .set(topoStats)
          .set(climStats);
      })(),
      ee.Feature(null, {}).set('valid', 0)
    );
  }));
});

// ------------------ فلت و فیلتر خروجی ------------------
var flattened = features.flatten().filter(ee.Filter.notNull([
  'NDVI_mean', 'BSI_mean', 'SAVI_mean', 'NDMI_mean', 'CI_mean',
  'OMI_mean', 'EVI_mean', 'SI_mean', 'RI_mean', 'CAI_mean', 'BI_mean'
]));

// ------------------ خروجی CSV ------------------
Export.table.toDrive({
  collection: flattened,
  description: 'BareSoil_TOPCLI_' + year + '_Part04',
  fileFormat: 'CSV'
});
